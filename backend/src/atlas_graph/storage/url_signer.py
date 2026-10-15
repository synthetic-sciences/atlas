"""JWT HS256 URL signing for Supabase Storage compatibility."""
import json
import base64
import hmac
import hashlib
import time
from atlas_graph import config


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
        f"{bucket}/{path}?token={token}"
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
