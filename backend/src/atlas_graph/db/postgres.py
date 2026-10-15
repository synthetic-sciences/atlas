"""PostgreSQL compatibility adapter extracted with the graph repositories."""
from __future__ import annotations
import functools
import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

class PgRowWrapper:
    """Row adapter that supports both mapping and positional access."""

    def __init__(self, values: dict[str, Any]):
        self._values = values
        self._keys = list(values.keys())

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._values[self._keys[key]]
        return self._values[key]

    def __iter__(self):
        return iter(self._values.values())

    def __len__(self) -> int:
        return len(self._values)

    def keys(self):
        return self._values.keys()

    def values(self):
        return self._values.values()

    def items(self):
        return self._values.items()

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return repr(self._values)


class PgCursorWrapper:
    """Minimal async cursor wrapper compatible with common aiosqlite usage."""

    def __init__(self, rows: list[PgRowWrapper] | None = None, *, rowcount: int = -1):
        self._rows = rows or []
        self._index = 0
        self.rowcount = rowcount
        if self._rows:
            self.description = [(key, None, None, None, None, None, None) for key in self._rows[0].keys()]
        else:
            self.description = []

    async def fetchone(self) -> PgRowWrapper | None:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    async def fetchall(self) -> list[PgRowWrapper]:
        if self._index >= len(self._rows):
            return []
        rows = self._rows[self._index :]
        self._index = len(self._rows)
        return rows

    async def close(self) -> None:
        return None


class PgConnectionWrapper:
    """Wraps asyncpg.Connection to provide an aiosqlite-compatible interface.

    The repo layer uses ``await db.execute(sql, params)`` and
    ``await db.execute_fetchall(sql, params)`` with ``?`` placeholders.
    This wrapper transparently converts to asyncpg's ``$1, $2, ...``
    numbered-parameter style.
    """

    def __init__(self, conn: Any):
        self._conn = conn

    async def execute(self, sql: str, params: tuple | list | None = None) -> PgCursorWrapper:
        """Execute a statement and return a cursor-like wrapper."""
        pg_sql = self._prepare_sql(sql)
        pg_params = self._normalize_params(params)
        if self._returns_rows(sql):
            if pg_params:
                rows = await self._conn.fetch(pg_sql, *pg_params)
            else:
                rows = await self._conn.fetch(pg_sql)
            return PgCursorWrapper([self._wrap_row(row) for row in rows], rowcount=len(rows))

        if pg_params:
            status = await self._conn.execute(pg_sql, *pg_params)
        else:
            status = await self._conn.execute(pg_sql)
        return PgCursorWrapper(rowcount=self._parse_rowcount(status))

    async def execute_fetchall(self, sql: str, params: tuple | list | None = None) -> list[dict]:
        """Execute a query and return all rows as dicts."""
        pg_sql = self._prepare_sql(sql)
        pg_params = self._normalize_params(params)
        if pg_params:
            rows = await self._conn.fetch(pg_sql, *pg_params)
        else:
            rows = await self._conn.fetch(pg_sql)
        return [self._normalize_row(row) for row in rows]

    async def execute_fetchone(self, sql: str, params: tuple | list | None = None) -> dict | None:
        """Execute a query and return the first row as a dict, or None."""
        pg_sql = self._prepare_sql(sql)
        pg_params = self._normalize_params(params)
        if pg_params:
            row = await self._conn.fetchrow(pg_sql, *pg_params)
        else:
            row = await self._conn.fetchrow(pg_sql)
        return self._normalize_row(row) if row else None

    async def executemany(self, sql: str, params_seq):
        """Execute a statement with many parameter sets."""
        pg_sql = self._prepare_sql(sql)
        normalized = [self._normalize_params(params) for params in params_seq]
        await self._conn.executemany(pg_sql, normalized)

    async def commit(self) -> None:
        """No-op - asyncpg auto-commits outside explicit transactions."""
        pass

    async def rollback(self) -> None:
        """No-op - use explicit transactions via self._conn.transaction()."""
        pass

    @property
    def raw(self) -> Any:
        """Escape hatch: access the underlying asyncpg.Connection directly."""
        return self._conn

    @staticmethod
    def _convert_placeholders(sql: str) -> str:
        """Convert ``?`` placeholders to ``$1, $2, ...`` for asyncpg."""
        idx = 0
        result: list[str] = []
        for char in sql:
            if char == "?":
                idx += 1
                result.append(f"${idx}")
            else:
                result.append(char)
        return "".join(result)

    @staticmethod
    def _returns_rows(sql: str) -> bool:
        prefix = sql.lstrip().upper()
        return prefix.startswith("SELECT") or prefix.startswith("WITH")

    @classmethod
    @functools.lru_cache(maxsize=1024)
    def _prepare_sql(cls, sql: str) -> str:
        """Rewrite SQLite dialect and ``?`` placeholders for asyncpg.

        Memoized on the statement text: the rewrite is a pure Python scan
        over 500-1000 character statements and hot requests run 15-20 of
        them, while the set of distinct statements is small and static.
        """
        return cls._convert_placeholders(cls._rewrite_sqlite_insert(sql))

    @staticmethod
    def _rewrite_sqlite_insert(sql: str) -> str:
        stripped = sql.lstrip()
        upper = stripped.upper()

        if upper.startswith("INSERT OR IGNORE INTO"):
            return stripped.replace("INSERT OR IGNORE INTO", "INSERT INTO", 1) + " ON CONFLICT DO NOTHING"

        if upper.startswith("INSERT OR REPLACE INTO"):
            match = re.match(
                r"INSERT OR REPLACE INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]+)\)\s*VALUES\s*\((.*)\)\s*",
                stripped,
                re.IGNORECASE | re.DOTALL,
            )
            if not match:
                return stripped

            table_name = match.group(1)
            columns = [column.strip() for column in match.group(2).split(",")]
            values_sql = match.group(3).strip()
            conflict_column = columns[0]
            update_columns = [
                f"{column} = EXCLUDED.{column}"
                for column in columns[1:]
            ]
            update_clause = ", ".join(update_columns) if update_columns else f"{conflict_column} = EXCLUDED.{conflict_column}"
            return (
                f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({values_sql}) "
                f"ON CONFLICT ({conflict_column}) DO UPDATE SET {update_clause}"
            )

        return stripped

    @staticmethod
    def _parse_rowcount(status: str) -> int:
        parts = status.split()
        if not parts:
            return -1
        try:
            return int(parts[-1])
        except ValueError:
            return -1

    @classmethod
    def _normalize_row(cls, row: Any) -> dict[str, Any]:
        return {key: cls._normalize_value(value) for key, value in dict(row).items()}

    @classmethod
    def _wrap_row(cls, row: Any) -> PgRowWrapper:
        return PgRowWrapper(cls._normalize_row(row))

    @classmethod
    def _normalize_params(cls, params: tuple | list | None) -> tuple | None:
        if params is None:
            return None
        if isinstance(params, (str, bytes, bytearray)):
            return (cls._normalize_param_value(params),)
        if not isinstance(params, (tuple, list)):
            return (cls._normalize_param_value(params),)
        return tuple(cls._normalize_param_value(value) for value in params)

    @classmethod
    def _normalize_param_value(cls, value: Any) -> Any:
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, bool):
            return value  # keep native bool for Postgres BOOLEAN columns
        if isinstance(value, int):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        if isinstance(value, str):
            parsed = cls._parse_iso_datetime(value)
            if parsed is not None:
                return parsed
        return value

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        candidate = value.strip()
        if not candidate or "T" not in candidate:
            return None
        normalized = candidate.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @classmethod
    def _normalize_value(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return value

