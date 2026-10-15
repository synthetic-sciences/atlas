"""Optional per-user GitHub authorization supplied by the host."""

from atlas_graph import config
from atlas_graph.runtime import host


async def get_user_access_token(db, *, user_id: str, owner: str | None = None):
    provider = host().github
    if provider is not None:
        return await provider().get_user_access_token(db, user_id=user_id, owner=owner)
    return config.GITHUB_TOKEN or None

