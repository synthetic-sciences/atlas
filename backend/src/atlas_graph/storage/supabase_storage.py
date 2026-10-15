"""
Supabase Storage integration for artifact files.

When SUPABASE_URL is configured, artifacts are stored in Supabase Storage bucket.
When not configured, falls back to local file storage (./data/blobs/).
"""
import logging
import httpx
from atlas_graph import config

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
            log.warning(
                "Bucket creation returned %s: %s", resp.status_code, resp.text
            )
        self._bucket_ensured = True

    async def upload(self, path: str, data: bytes, content_type: str) -> str:
        """Upload file with upsert semantics. Returns storage path."""
        if self.use_supabase:
            async with httpx.AsyncClient() as client:
                await self._ensure_bucket(client)
                resp = await client.post(
                    f"{self.base_url}/object/{self.bucket}/{path}",
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
                        f"{self.base_url}/object/{self.bucket}/{path}",
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
            local_path = config.BLOBS_DIR / path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(data)
            return path

    async def download(self, path: str) -> bytes:
        """Download file bytes."""
        if self.use_supabase:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}/object/{self.bucket}/{path}",
                    headers=self.headers,
                )
                resp.raise_for_status()
                return resp.content
        else:
            local_path = config.BLOBS_DIR / path
            return local_path.read_bytes()

    async def delete(self, path: str) -> None:
        """Delete a file from storage."""
        if self.use_supabase:
            async with httpx.AsyncClient() as client:
                resp = await client.delete(
                    f"{self.base_url}/object/{self.bucket}/{path}",
                    headers=self.headers,
                )
                # Ignore errors on delete (file may already be gone)
        else:
            local_path = config.BLOBS_DIR / path
            if local_path.exists():
                local_path.unlink()

    async def signed_url(self, path: str, expires_in: int | None = None) -> str:
        """Generate a signed download URL via the Supabase REST API."""
        if not self.use_supabase:
            return f"/api/artifacts/download/{path}"

        ttl = expires_in or config.SIGNED_URL_TTL_SECONDS
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/object/sign/{self.bucket}/{path}",
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
        if self.use_supabase:
            return self._sign_supabase_url(path)
        else:
            return f"/api/artifacts/download/{path}"

    def _sign_supabase_url(self, path: str) -> str:
        """Sign a Supabase storage URL with JWT HS256."""
        import json, base64, hmac, hashlib, time

        now = int(time.time())
        payload = {
            "url": f"{self.bucket}/{path}",
            "iat": now,
            "exp": now + config.SIGNED_URL_TTL_SECONDS,
        }

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(
            json.dumps(payload).encode()
        ).rstrip(b"=").decode()
        signing_input = f"{header}.{body}".encode()
        sig = base64.urlsafe_b64encode(
            hmac.new(
                config.SUPABASE_JWT_SECRET.encode(),
                signing_input,
                hashlib.sha256,
            ).digest()
        ).rstrip(b"=").decode()

        token = f"{header}.{body}.{sig}"
        return (
            f"{config.SUPABASE_URL}/storage/v1/object/sign/"
            f"{self.bucket}/{path}?token={token}"
        )


# Global singleton
storage = StorageClient()
