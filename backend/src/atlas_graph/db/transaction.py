"""Keep repository helpers' commits inside one graph mutation."""

from contextlib import asynccontextmanager
from uuid import uuid4


class _Connection:
    def __init__(self, database):
        self.database = database

    def __getattr__(self, name):
        return getattr(self.database, name)

    async def commit(self):
        # Repository helpers predate multi-step mutations and commit eagerly.
        # Only the enclosing transaction may publish their combined changes.
        return None


@asynccontextmanager
async def transaction(db):
    raw = getattr(db, "raw", None)
    if raw is not None:
        async with raw.transaction():
            yield _Connection(db)
        return

    nested = db.in_transaction
    savepoint = f"graph_{uuid4().hex}"
    await db.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
    try:
        yield _Connection(db)
        if nested:
            await db.execute(f"RELEASE SAVEPOINT {savepoint}")
        else:
            await db.commit()
    except BaseException:
        if nested:
            await db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            await db.execute(f"RELEASE SAVEPOINT {savepoint}")
        else:
            await db.rollback()
        raise
