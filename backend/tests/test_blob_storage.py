import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from atlas_graph import config
from atlas_graph.storage import local, url_signer
from atlas_graph.storage.supabase_storage import StorageClient


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/private",
        "..",
        "../private",
        "a/../../private",
        "a//b",
        "a/./b",
        "a\\b",
        "a\x00b",
    ],
)
async def test_blob_operations_reject_escaping_or_ambiguous_paths(client, path):
    storage = StorageClient()
    for operation in [
        lambda: storage.upload(path, b"private", "text/plain"),
        lambda: storage.download(path),
        lambda: storage.delete(path),
    ]:
        with pytest.raises(ValueError, match="storage path"):
            await operation()
    with pytest.raises(ValueError, match="storage path"):
        storage.get_signed_url(path)


async def test_blob_roundtrip_atomic_replacement_and_failed_write_preserve_bytes(
    client, monkeypatch
):
    storage = StorageClient()
    await storage.upload("nested/evidence.txt", b"original", "text/plain")
    assert await storage.download("nested/evidence.txt") == b"original"
    original = os.replace

    def fail(*args, **kwargs):
        raise OSError("fixture interrupted atomic replacement")

    monkeypatch.setattr(local.os, "replace", fail)
    with pytest.raises(OSError, match="fixture"):
        await storage.upload("nested/evidence.txt", b"partial", "text/plain")
    assert await storage.download("nested/evidence.txt") == b"original"
    assert {p.name for p in (config.BLOBS_DIR / "nested").iterdir()} == {"evidence.txt"}
    monkeypatch.setattr(local.os, "replace", original)
    await storage.upload("nested/evidence.txt", b"replacement", "text/plain")
    assert await storage.download("nested/evidence.txt") == b"replacement"
    assert (config.BLOBS_DIR / "nested/evidence.txt").stat().st_mode & 0o077 == 0
    await storage.delete("nested/evidence.txt")
    await storage.delete("nested/evidence.txt")
    with pytest.raises(FileNotFoundError):
        await storage.download("nested/evidence.txt")


async def test_blob_symlinks_cannot_read_write_or_delete_outside_root(client, tmp_path):
    storage = StorageClient()
    outside = tmp_path / "outside"
    outside.mkdir()
    private = outside / "private.txt"
    private.write_bytes(b"outside secret")
    config.BLOBS_DIR.mkdir(exist_ok=True)
    (config.BLOBS_DIR / "link").symlink_to(outside, target_is_directory=True)
    for operation in [
        lambda: storage.upload("link/private.txt", b"overwrite", "text/plain"),
        lambda: storage.download("link/private.txt"),
        lambda: storage.delete("link/private.txt"),
    ]:
        with pytest.raises(ValueError, match="storage path"):
            await operation()
    assert private.read_bytes() == b"outside secret"
    (config.BLOBS_DIR / "file.txt").symlink_to(private)
    with pytest.raises(ValueError, match="storage path"):
        await storage.download("file.txt")
    await storage.upload("file.txt", b"graph owned", "text/plain")
    assert private.read_bytes() == b"outside secret"
    assert await storage.download("file.txt") == b"graph owned"


async def artifact(client, filename="evidence.txt", data=b"evidence bytes"):
    project = (
        await client.post("/api/v1/projects", json={"title": "Blob ownership"})
    ).json()["project_id"]
    prepared = await client.post(
        f"/api/v1/nodes/{project}/artifacts/uploads/prepare",
        json={
            "expected_revision": 0,
            "items": [
                {
                    "filename": filename,
                    "artifact_type": "binary",
                    "media_type": "application/octet-stream",
                }
            ],
        },
    )
    assert prepared.status_code == 201, prepared.text
    batch = prepared.json()
    uploaded = await client.put(
        batch["items"][0]["upload_url"],
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code in {200, 201, 204}, uploaded.text
    finalized = await client.post(
        f"/api/v1/nodes/{project}/artifacts/uploads/finalize",
        json={"batch_token": batch["batch_token"]},
    )
    assert finalized.status_code == 200, finalized.text
    response = await client.get(f"/api/v1/nodes/{project}/artifacts")
    assert response.status_code == 200, response.text
    return response.json()[0]


async def test_graph_signed_blob_url_works_without_bearer_but_plain_url_requires_auth(
    client,
):
    item = await artifact(client)
    url = item["storage_url"]
    assert "?token=" in url
    downloaded = await client.get(url, headers={"Authorization": ""})
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == b"evidence bytes"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    plain = await client.get(urlsplit(url).path, headers={"Authorization": ""})
    assert plain.status_code == 401
    authenticated = await client.get(urlsplit(url).path)
    assert authenticated.status_code == 200


async def test_signed_blob_cannot_read_another_artifact_or_survive_expiry_or_key_change(
    client, monkeypatch
):
    first = await artifact(client)
    second = await artifact(client, data=b"other evidence")
    url = first["storage_url"]
    swapped = url.replace(first["storage_path"], second["storage_path"])
    assert (await client.get(swapped, headers={"Authorization": ""})).status_code == 401
    with monkeypatch.context() as context:
        context.setenv("ATLAS_SIGNING_SECRET", uuid4().hex)
        assert (await client.get(url, headers={"Authorization": ""})).status_code == 401
    now = url_signer.time.time()
    monkeypatch.setattr(url_signer.time, "time", lambda: now + 3601)
    assert (await client.get(url, headers={"Authorization": ""})).status_code == 401


async def test_signed_executable_blob_is_sandboxed_and_forced_to_download(client):
    item = await artifact(client, "evidence.html", b"<script>private()</script>")
    downloaded = await client.get(item["storage_url"], headers={"Authorization": ""})
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/octet-stream"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert (
        downloaded.headers["content-security-policy"] == "sandbox; default-src 'none'"
    )


@pytest.mark.parametrize("ttl", [0, -1, 3601, True, 1.5])
async def test_blob_url_lifetimes_are_bounded(client, ttl):
    with pytest.raises(ValueError, match="lifetime"):
        url_signer.blob_url("safe/evidence.txt", ttl)


async def test_storage_signatures_are_not_interchangeable_with_other_token_purposes(
    client,
):
    from urllib.parse import parse_qs

    path = "safe/evidence.txt"
    storage_token = parse_qs(urlsplit(url_signer.sign_url("blobs", path)).query)[
        "token"
    ][0]
    assert url_signer.verify_signed_token(storage_token)
    assert url_signer.verify_blob(storage_token, path) is False
    download_token = parse_qs(urlsplit(url_signer.blob_url(path)).query)["token"][0]
    assert url_signer.verify_blob(download_token, path)
    assert url_signer.verify_blob(download_token + "altered", path) is False


async def test_blob_special_files_are_rejected_without_blocking(client):
    config.BLOBS_DIR.mkdir(exist_ok=True)
    os.mkfifo(config.BLOBS_DIR / "pipe")
    with pytest.raises(ValueError, match="storage path"):
        await StorageClient().download("pipe")


async def test_hosted_startup_rejects_a_shared_storage_administrator_key(monkeypatch):
    from atlas_graph.hosted import create_app

    monkeypatch.setenv("ATLAS_MODE", "hosted")
    monkeypatch.setenv("ATLAS_SIGNING_SECRET", uuid4().hex)
    monkeypatch.setenv(
        "ATLAS_SUPABASE_SERVICE_ROLE_KEY", "fixture-admin-key-must-stay-in-dashboard"
    )
    with pytest.raises(RuntimeError, match="graph-owned blob storage"):
        create_app()


async def test_hosted_startup_rejects_a_weak_signing_secret(monkeypatch):
    from atlas_graph.hosted import create_app

    monkeypatch.setenv("ATLAS_MODE", "hosted")
    monkeypatch.setenv("ATLAS_SIGNING_SECRET", "weak")
    with pytest.raises(RuntimeError, match="own signing secret"):
        create_app()


async def test_optional_supabase_signing_retains_the_existing_bucket_claim(client, monkeypatch):
    from urllib.parse import parse_qs

    monkeypatch.setenv("ATLAS_SUPABASE_URL", "https://storage.example")
    monkeypatch.setenv("ATLAS_SUPABASE_SERVICE_ROLE_KEY", "fixture-direct-storage-key")
    storage = StorageClient()
    assert storage.use_supabase
    path = "artifacts/evidence #1?.txt"
    url = storage.get_signed_url(path)
    assert url.startswith("https://storage.example/storage/v1/object/sign/blobs/artifacts/evidence%20%231%3F.txt?")
    token = parse_qs(urlsplit(url).query)["token"][0]
    assert url_signer.verify_signed_token(token)["url"] == f"blobs/{path}"
    assert url_signer.verify_blob(token, path) is False
