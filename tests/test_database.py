import os
import sys
import tempfile

import pytest

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

from shared.database import SQLiteDB, create_database, _adapt_query, _sqlite_to_pg


_tmpdir = tempfile.mkdtemp()

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        value REAL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS idx_items_name ON items(name)",
]


_db_counter = 0

@pytest.fixture
async def db():
    global _db_counter
    _db_counter += 1
    path = os.path.join(_tmpdir, f"test_db_layer_{_db_counter}.db")
    database = SQLiteDB(path)
    await database.init(SCHEMA)
    return database


class TestSQLiteDB:
    async def test_init_creates_table(self, db):
        async with db.connection() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM items")
        assert count == 0

    async def test_insert_and_fetchone(self, db):
        async with db.connection() as conn:
            await conn.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("alpha", 1.5))
            await conn.commit()
            row = await conn.fetchone("SELECT * FROM items WHERE name = ?", ("alpha",))
        assert row["name"] == "alpha"
        assert row["value"] == 1.5

    async def test_insert_and_fetchall(self, db):
        async with db.connection() as conn:
            await conn.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("a", 1.0))
            await conn.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("b", 2.0))
            await conn.commit()
            rows = await conn.fetchall("SELECT * FROM items ORDER BY name")
        assert len(rows) == 2
        assert rows[0]["name"] == "a"
        assert rows[1]["name"] == "b"

    async def test_fetchval(self, db):
        async with db.connection() as conn:
            await conn.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("x", 42.0))
            await conn.commit()
            val = await conn.fetchval("SELECT value FROM items WHERE name = ?", ("x",))
        assert val == 42.0

    async def test_fetchone_returns_none_for_missing(self, db):
        async with db.connection() as conn:
            row = await conn.fetchone("SELECT * FROM items WHERE name = ?", ("nonexistent",))
        assert row is None

    async def test_fetchval_returns_none_for_missing(self, db):
        async with db.connection() as conn:
            val = await conn.fetchval("SELECT value FROM items WHERE name = ?", ("nonexistent",))
        assert val is None

    async def test_health_check_healthy(self, db):
        result = await db.health_check()
        assert result["ok"] is True
        assert result["backend"] == "sqlite"

    async def test_health_check_unhealthy(self):
        bad_db = SQLiteDB("/nonexistent/path/db.sqlite")
        result = await bad_db.health_check()
        assert result["ok"] is False

    async def test_multiple_connections(self, db):
        async with db.connection() as conn1:
            await conn1.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("mc1", 1.0))
            await conn1.commit()
        async with db.connection() as conn2:
            row = await conn2.fetchone("SELECT * FROM items WHERE name = ?", ("mc1",))
        assert row is not None

    async def test_unicode_data(self, db):
        async with db.connection() as conn:
            await conn.execute("INSERT INTO items (name, value) VALUES (?, ?)", ("日本語テスト", 99.0))
            await conn.commit()
            row = await conn.fetchone("SELECT * FROM items WHERE name = ?", ("日本語テスト",))
        assert row["name"] == "日本語テスト"


class TestQueryAdaptation:
    def test_no_params(self):
        query, params = _adapt_query("SELECT * FROM items", ())
        assert query == "SELECT * FROM items"
        assert params == ()

    def test_single_param(self):
        query, params = _adapt_query("SELECT * FROM items WHERE id = ?", (1,))
        assert query == "SELECT * FROM items WHERE id = $1"
        assert params == (1,)

    def test_multiple_params(self):
        query, params = _adapt_query(
            "INSERT INTO items (name, value) VALUES (?, ?)", ("test", 1.0)
        )
        assert query == "INSERT INTO items (name, value) VALUES ($1, $2)"
        assert params == ("test", 1.0)

    def test_three_params(self):
        query, params = _adapt_query(
            "SELECT * FROM t WHERE a = ? AND b = ? AND c = ?", (1, 2, 3)
        )
        assert "$1" in query and "$2" in query and "$3" in query


class TestDDLTranslation:
    def test_autoincrement_removed(self):
        result = _sqlite_to_pg("id INTEGER PRIMARY KEY AUTOINCREMENT")
        assert "AUTOINCREMENT" not in result
        assert "SERIAL PRIMARY KEY" in result

    def test_integer_primary_key_becomes_serial(self):
        result = _sqlite_to_pg("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        assert "SERIAL PRIMARY KEY" in result

    def test_if_not_exists_preserved(self):
        result = _sqlite_to_pg("CREATE TABLE IF NOT EXISTS t (id TEXT)")
        assert "IF NOT EXISTS" in result


class TestCreateDatabase:
    def test_creates_sqlite_by_default(self):
        db = create_database(db_path="/tmp/test.db")
        assert isinstance(db, SQLiteDB)

    def test_creates_sqlite_with_path(self):
        db = create_database(db_path="/tmp/custom.db")
        assert db.path == "/tmp/custom.db"
