import os
import logging
from contextlib import asynccontextmanager

import aiosqlite

logger = logging.getLogger("database")

DB_BACKEND = os.getenv("DB_BACKEND", "sqlite")


async def enable_wal(db_path: str):
    """Enable WAL mode and set busy timeout for SQLite database."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")


def _parse_dsn(dsn: str) -> dict:
    """Extract host, port, dbname, user, password from a PostgreSQL DSN."""
    from urllib.parse import urlparse
    parsed = urlparse(dsn)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "database": (parsed.path or "/").lstrip("/"),
        "user": parsed.username or "postgres",
        "password": parsed.password or "",
    }


class SQLiteDB:
    def __init__(self, path: str):
        self.path = path

    async def init(self, schema_sql: list[str]):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            for stmt in schema_sql:
                await db.execute(stmt)
            await db.commit()
        logger.info("SQLite database initialized at %s", self.path)

    @asynccontextmanager
    async def connection(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            yield _SQLiteConnection(db)

    async def health_check(self) -> dict:
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute("SELECT 1")
            return {"ok": True, "backend": "sqlite"}
        except Exception as e:
            return {"ok": False, "backend": "sqlite", "error": str(e)}


class _SQLiteConnection:
    def __init__(self, db):
        self._db = db

    async def execute(self, query: str, params: tuple = ()):
        await self._db.execute(query, params)

    async def fetchone(self, query: str, params: tuple = ()):
        cursor = await self._db.execute(query, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def fetchall(self, query: str, params: tuple = ()):
        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def fetchval(self, query: str, params: tuple = ()):
        cursor = await self._db.execute(query, params)
        row = await cursor.fetchone()
        return row[0] if row else None

    async def commit(self):
        await self._db.commit()


class PostgresDB:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool = None

    async def init(self, schema_sql: list[str]):
        import asyncpg
        params = _parse_dsn(self.dsn)
        self._pool = await asyncpg.create_pool(**params, min_size=2, max_size=10)
        async with self._pool.acquire() as conn:
            for stmt in schema_sql:
                pg_stmt = _sqlite_to_pg(stmt)
                await conn.execute(pg_stmt)
        logger.info("PostgreSQL database initialized at %s", params["host"])

    @asynccontextmanager
    async def connection(self):
        async with self._pool.acquire() as conn:
            yield _PostgresConnection(conn)

    async def health_check(self) -> dict:
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return {"ok": True, "backend": "postgres"}
        except Exception as e:
            return {"ok": False, "backend": "postgres", "error": str(e)}

    async def close(self):
        if self._pool:
            await self._pool.close()


class _PostgresConnection:
    def __init__(self, conn):
        self._conn = conn
        self._tx = None

    async def execute(self, query: str, params: tuple = ()):
        pg_query, pg_params = _adapt_query(query, params)
        await self._conn.execute(pg_query, *pg_params)

    async def fetchone(self, query: str, params: tuple = ()):
        pg_query, pg_params = _adapt_query(query, params)
        row = await self._conn.fetchrow(pg_query, *pg_params)
        return dict(row) if row else None

    async def fetchall(self, query: str, params: tuple = ()):
        pg_query, pg_params = _adapt_query(query, params)
        rows = await self._conn.fetch(pg_query, *pg_params)
        return [dict(r) for r in rows]

    async def fetchval(self, query: str, params: tuple = ()):
        pg_query, pg_params = _adapt_query(query, params)
        return await self._conn.fetchval(pg_query, *pg_params)

    async def commit(self):
        pass


def _adapt_query(query: str, params: tuple) -> tuple:
    """Convert SQLite ?-style placeholders to PostgreSQL $N-style."""
    pg_query = query
    for i in range(len(params), 0, -1):
        pass
    parts = []
    idx = 1
    i = 0
    while i < len(pg_query):
        if pg_query[i] == "?" and (i == 0 or pg_query[i - 1] != "'"):
            parts.append(f"${idx}")
            idx += 1
        else:
            parts.append(pg_query[i])
        i += 1
    return "".join(parts), params


def _sqlite_to_pg(stmt: str) -> str:
    """Rough translation of common SQLite DDL to PostgreSQL."""
    result = stmt
    result = result.replace("AUTOINCREMENT", "")
    result = result.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
    if "IF NOT EXISTS" not in result.upper() and "CREATE TABLE" in result.upper():
        result = result.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
    if "IF NOT EXISTS" not in result.upper() and "CREATE INDEX" in result.upper():
        result = result.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1)
    return result


def create_database(db_path: str = None, dsn: str = None) -> SQLiteDB | PostgresDB:
    if DB_BACKEND == "postgres" and dsn:
        return PostgresDB(dsn)
    path = db_path or "/data/default.db"
    return SQLiteDB(path)
