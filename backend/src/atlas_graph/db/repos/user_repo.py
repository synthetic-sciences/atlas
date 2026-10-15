"""Graph author profiles; this store does not issue account credentials."""


async def get_user_by_github_username(db, github_username: str) -> dict | None:
    if not github_username or not github_username.strip():
        return None
    cursor = await db.execute(
        "SELECT * FROM users WHERE LOWER(github_username) = LOWER(?) ORDER BY created_at ASC LIMIT 1",
        (github_username.strip(),),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None

