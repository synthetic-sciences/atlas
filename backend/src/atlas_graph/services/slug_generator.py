"""
Generate human-friendly slug names in the format: {adjective}-{noun}-{4-digit-number}.

Each slug is checked for uniqueness against the nodes table before being returned.
"""

import random

ADJECTIVES = [
    "bold", "calm", "dark", "deep", "dry", "fair", "fast", "firm", "flat", "free",
    "glad", "gold", "gray", "keen", "kind", "late", "lean", "long", "loud", "mild",
    "neat", "next", "pale", "pure", "rare", "raw", "real", "rich", "ripe", "safe",
    "slim", "slow", "soft", "tall", "thin", "true", "vast", "warm", "weak", "wide",
    "wise", "able", "blue", "cool", "even", "fine", "full", "good", "high", "open",
]

NOUNS = [
    "arc", "ash", "bay", "beam", "bell", "bird", "bone", "cave", "clay", "claw",
    "coal", "cone", "cord", "core", "dawn", "dew", "dock", "dome", "drum", "dusk",
    "edge", "elm", "fade", "fern", "fire", "flaw", "foam", "gate", "gale", "glen",
    "glow", "haze", "helm", "husk", "jade", "knot", "lake", "leaf", "lime", "mist",
    "moss", "nest", "node", "opal", "palm", "pine", "pond", "reef", "root", "sage",
]


async def generate_slug(db) -> str:
    """
    Generate a unique slug in the form adjective-noun-NNNN.

    Parameters
    ----------
    db : aiosqlite.Connection
        An open aiosqlite database connection.

    Returns
    -------
    str
        A unique slug string.
    """
    for _ in range(100):
        adj = random.choice(ADJECTIVES)
        noun = random.choice(NOUNS)
        number = f"{random.randint(0, 9999):04d}"
        slug = f"{adj}-{noun}-{number}"

        cursor = await db.execute(
            "SELECT 1 FROM nodes WHERE slug_name = ? LIMIT 1", (slug,)
        )
        row = await cursor.fetchone()
        if row is None:
            return slug

    raise RuntimeError("Failed to generate a unique slug after 100 attempts")
