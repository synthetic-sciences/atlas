"""JWT HS256 URL signing for Supabase Storage compatibility."""
import json
import base64
import hmac
import hashlib
import time
from urllib.parse import quote
from atlas_graph import config


def blob_url(path: str, ttl: int | None = None) -> str:
    from atlas_graph.storage.local import path as validate

    path = validate(path)
    ttl = config.SIGNED_URL_TTL_SECONDS if ttl is None else ttl
    if type(ttl) is not int or not 1 <= ttl <= config.SIGNED_URL_TTL_SECONDS:
        raise ValueError("Invalid artifact URL lifetime")
    now = int(time.time())
    header = _b64url_encode(b'{"alg":"HS256","typ":"JWT"}')
    body = _b64url_encode(json.dumps({
        "kind": "artifact-download-v1", "path": path, "iat": now, "exp": now + ttl,
    }, separators=(",", ":")).encode())
    signature = _b64url_encode(hmac.new(
        config.SUPABASE_JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256,
    ).digest())
    return f"/api/artifacts/download/{quote(path, safe='/')}?token={header}.{body}.{signature}"


def verify_blob(token: str, path: str) -> bool:
    if len(token) > 16_384:
        return False
    payload = verify_signed_token(token)
    if not isinstance(payload, dict):
        return False
    issued, expires = payload.get("iat"), payload.get("exp")
    return bool(
        payload.get("kind") == "artifact-download-v1" and payload.get("path") == path
        and type(issued) is int and type(expires) is int
        and issued <= time.time() < expires
        and 0 < expires - issued <= config.SIGNED_URL_TTL_SECONDS
    )


def _b64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    """Base64url decode with padding restoration."""
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


def sign_url(bucket: str, path: str, ttl_seconds: int | None = None) -> str:
    """Create a signed URL for a Supabase Storage object.

    Parameters
    ----------
    bucket:
        Storage bucket name.
    path:
        Object path within the bucket.
    ttl_seconds:
        Lifetime in seconds (defaults to ``config.SIGNED_URL_TTL_SECONDS``).

    Returns
    -------
    str
        Full signed URL including ``?token=...`` query parameter.
    """
    if ttl_seconds is None:
        ttl_seconds = config.SIGNED_URL_TTL_SECONDS

    now = int(time.time())
    payload = {
        "url": f"{bucket}/{path}",
        "iat": now,
        "exp": now + ttl_seconds,
    }

    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{header}.{body}".encode()
    sig = _b64url_encode(
        hmac.new(
            config.SUPABASE_JWT_SECRET.encode(),
            signing_input,
            hashlib.sha256,
        ).digest()
    )

    token = f"{header}.{body}.{sig}"
    return (
        f"{config.SUPABASE_URL}/storage/v1/object/sign/"
        f"{quote(bucket, safe='')}/{quote(path, safe='/')}?token={token}"
    )


def verify_signed_token(token: str) -> dict | None:
    """Verify a signed URL token (HS256).

    Returns the payload dict on success, or ``None`` if the token is
    invalid or expired.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        # Verify header
        header = json.loads(_b64url_decode(parts[0]))
        if header.get("alg") != "HS256":
            return None

        # Verify signature
        signing_input = f"{parts[0]}.{parts[1]}".encode()
        expected_sig = hmac.new(
            config.SUPABASE_JWT_SECRET.encode(),
            signing_input,
            hashlib.sha256,
        ).digest()
        actual_sig = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        # Decode and check expiry
        payload = json.loads(_b64url_decode(parts[1]))
        exp = payload.get("exp")
        if exp and time.time() > exp:
            return None

        return payload
    except Exception:
        return None
