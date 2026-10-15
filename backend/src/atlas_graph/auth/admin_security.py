"""Step-up checks supplied by the authenticated hosting application."""

from fastapi import HTTPException

from atlas_graph.runtime import host


def require_fresh_mfa(user: dict) -> None:
    check = host().mfa
    if check is not None:
        check(user)
        return
    raise HTTPException(status_code=403, detail="Administrator step-up is unavailable")

