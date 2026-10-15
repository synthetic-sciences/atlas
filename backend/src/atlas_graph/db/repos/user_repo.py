"""Graph author profiles; this store does not issue account credentials."""


async def get_user_by_github_username(db, github_username: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM users WHERE github_username = ?", (github_username,))
    row = await cursor.fetchone()
    return dict(row) if row else None

