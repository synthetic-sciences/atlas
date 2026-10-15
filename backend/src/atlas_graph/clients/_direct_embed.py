"""Optional direct embeddings for local and self-hosted graphs."""

import os

import httpx

EMBED_DIM = 1536


class OpenAIEmbedError(Exception):
    pass


class ConfigurationError(OpenAIEmbedError):
    pass


class EmbeddingBillingError(OpenAIEmbedError):
    pass


async def embed_batch(texts: list[str], *, db=None, user_id: str | None = None, endpoint: str = "embed_batch") -> list[list[float]]:
    if not texts:
        return []
    key = os.environ.get("ATLAS_EMBEDDING_API_KEY", "").strip()
    if not key:
        raise ConfigurationError("An embedding provider is not configured")
    base = os.environ.get("ATLAS_EMBEDDING_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base}/embeddings",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": os.environ.get("ATLAS_EMBEDDING_MODEL", "text-embedding-3-small"), "input": texts},
        )
    if response.status_code != 200:
        raise OpenAIEmbedError(f"Embedding provider returned HTTP {response.status_code}")
    items = response.json().get("data")
    if not isinstance(items, list) or len(items) != len(texts):
        raise OpenAIEmbedError("Embedding provider returned an invalid batch")
    ordered = sorted(items, key=lambda item: item.get("index", 0))
    vectors = [item.get("embedding") for item in ordered]
    if any(not isinstance(vector, list) or len(vector) != EMBED_DIM for vector in vectors):
        raise OpenAIEmbedError("Embedding dimensions do not match the graph index")
    return [[float(value) for value in vector] for vector in vectors]


async def embed_text(text: str, *, db=None, user_id: str | None = None, endpoint: str = "embed") -> list[float]:
    return (await embed_batch([text], db=db, user_id=user_id, endpoint=endpoint))[0]


async def close_http() -> None:
    return None

