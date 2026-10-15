"""
Supabase Storage integration for artifact files.

When SUPABASE_URL is configured, artifacts are stored in Supabase Storage bucket.
When not configured, falls back to local file storage (./data/blobs/).
"""
import logging
import asyncio
from urllib.parse import quote
import httpx
from atlas_graph import config
from atlas_graph.storage import local
from atlas_graph.storage.url_signer import blob_url, sign_url

log = logging.getLogger(__name__)


class StorageClient:
    def __init__(self):
        self.use_supabase = bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY)
        if self.use_supabase:
            self.base_url = f"{config.SUPABASE_URL}/storage/v1"
            self.headers = {
                "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
            }
            self.bucket = config.SUPABASE_STORAGE_BUCKET
            self._bucket_ensured = False

    async def _ensure_bucket(self, client: httpx.AsyncClient) -> None:
        """Create the storage bucket if it doesn't already exist."""
        if self._bucket_ensured:
            return
        resp = await client.post(
            f"{self.base_url}/bucket",
            json={"id": self.bucket, "name": self.bucket, "public": False},
            headers={**self.headers, "Content-Type": "application/json"},
        )
        if resp.status_code in (409, 400) and "already exists" in resp.text.lower():
            # Bucket already exists - that's fine
            pass
        elif resp.status_code in (409, 400) and "Duplicate" in resp.text:
            # Supabase sometimes returns 400 with a Duplicate error body
            pass
        elif resp.is_success:
            log.info("Created storage bucket %r", self.bucket)
        else:
            resp.raise_for_status()
        self._bucket_ensured = True

    async def upload(self, path: str, data: bytes, content_type: str) -> str:
        """Upload file with upsert semantics. Returns storage path."""
        path = local.path(path)
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise ValueError("Artifact exceeds the upload limit")
        if self.use_supabase:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
                await self._ensure_bucket(client)
                resp = await client.post(
                    f"{self.base_url}/object/{quote(self.bucket, safe='')}/{quote(path, safe='/')}",
                    content=data,
                    headers={
                        **self.headers,
                        "Content-Type": content_type,
                        "x-upsert": "true",
                    },
                )
                # Handle 409 (object exists) gracefully - retry as update
                if resp.status_code == 409:
                    resp = await client.put(
                        f"{self.base_url}/object/{quote(self.bucket, safe='')}/{quote(path, safe='/')}",
                        content=data,
                        headers={
                            **self.headers,
                            "Content-Type": content_type,
                            "x-upsert": "true",
                        },
                    )
                resp.raise_for_status()
            return path
        else:
            # Local storage fallback
            await asyncio.to_thread(local.upload, path, data)
            return path

    async def download(self, path: str) -> bytes:
        """Download file bytes."""
        path = local.path(path)
        if self.use_supabase:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
                resp = await client.get(
                    f"{self.base_url}/object/{quote(self.bucket, safe='')}/{quote(path, safe='/')}",
                    headers=self.headers,
                )
                resp.raise_for_status()
                return resp.content
        else:
            return await asyncio.to_thread(local.download, path)

    async def delete(self, path: str) -> None:
        """Delete a file from storage."""
        path = local.path(path)
        if self.use_supabase:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
                resp = await client.delete(
                    f"{self.base_url}/object/{quote(self.bucket, safe='')}/{quote(path, safe='/')}",
                    headers=self.headers,
                )
                if resp.status_code != 404:
                    resp.raise_for_status()
        else:
            await asyncio.to_thread(local.delete, path)

    async def signed_url(self, path: str, expires_in: int | None = None) -> str:
        """Generate a signed download URL via the Supabase REST API."""
        path = local.path(path)
        if not self.use_supabase:
            return blob_url(path, expires_in)

        ttl = expires_in or config.SIGNED_URL_TTL_SECONDS
        async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
            resp = await client.post(
                f"{self.base_url}/object/sign/{quote(self.bucket, safe='')}/{quote(path, safe='/')}",
                json={"expiresIn": ttl},
                headers={**self.headers, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            token = resp.json().get("signedURL", "")
            # The signedURL is a relative path - prepend base
            if token.startswith("/"):
                return f"{config.SUPABASE_URL}/storage/v1{token}"
            return token

    def get_signed_url(self, path: str) -> str:
        """Synchronous signed URL via local JWT signing (1-hour TTL).

        Prefer the async ``signed_url`` method when possible - it uses the
        official Supabase sign endpoint.  This sync helper is kept for
        backwards compatibility where an event loop isn't available.
        """
        path = local.path(path)
        if self.use_supabase:
            return self._sign_supabase_url(path)
        else:
            return blob_url(path)

    def _sign_supabase_url(self, path: str) -> str:
        return sign_url(self.bucket, path)


# Global singleton
storage = StorageClient()
