"""Tests for the database backup utility."""

import os
import sqlite3
import sys
import tempfile

import pytest

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)


@pytest.fixture
def backup_env(tmp_path):
    db_dir = tmp_path / "dbs"
    db_dir.mkdir()
    backup_dir = tmp_path / "backups"

    db_path = str(db_dir / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items (name) VALUES ('alpha')")
    conn.execute("INSERT INTO items (name) VALUES ('beta')")
    conn.commit()
    conn.close()

    env = {
        "ORCHESTRATOR_DB_PATH": db_path,
        "BILLING_DB_PATH": str(db_dir / "nonexistent.db"),
        "BACKUP_DIR": str(backup_dir),
        "MAX_BACKUPS": "3",
    }
    return env, db_path, backup_dir


class TestBackupAll:
    def test_backs_up_existing_db(self, backup_env):
        env, db_path, backup_dir = backup_env
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)

            import importlib
            import scripts.backup_databases as bk
            importlib.reload(bk)

            result = bk.backup_all()

        assert result["timestamp"]
        dbs = result["databases"]
        orch = next(d for d in dbs if d["service"] == "orchestrator")
        assert orch["status"] == "ok"
        assert orch["size_mb"] >= 0

    def test_skips_missing_db(self, backup_env):
        env, _, backup_dir = backup_env
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)

            import importlib
            import scripts.backup_databases as bk
            importlib.reload(bk)

            result = bk.backup_all()

        billing = next(d for d in result["databases"] if d["service"] == "billing")
        assert billing["status"] == "skipped"

    def test_backup_data_integrity(self, backup_env):
        env, db_path, backup_dir = backup_env
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)

            import importlib
            import scripts.backup_databases as bk
            importlib.reload(bk)

            result = bk.backup_all()

        ts_dir = backup_dir / result["timestamp"]
        backup_db = str(ts_dir / "orchestrator.db")
        conn = sqlite3.connect(backup_db)
        rows = conn.execute("SELECT name FROM items ORDER BY name").fetchall()
        conn.close()
        assert [r[0] for r in rows] == ["alpha", "beta"]

    def test_prune_old_backups(self, backup_env):
        env, _, backup_dir = backup_env
        with pytest.MonkeyPatch.context() as mp:
            for k, v in env.items():
                mp.setenv(k, v)

            import importlib
            import scripts.backup_databases as bk
            importlib.reload(bk)

            for _ in range(5):
                bk.backup_all()

        dirs = list(backup_dir.iterdir())
        assert len(dirs) <= 3
