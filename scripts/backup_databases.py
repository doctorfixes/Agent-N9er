#!/usr/bin/env python3
"""Backup all Agent N9er SQLite databases to a timestamped directory."""

import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SERVICES = {
    "orchestrator": os.getenv("ORCHESTRATOR_DB_PATH", "/data/orchestrator.db"),
    "marketplace": os.getenv("DB_PATH", "/data/marketplace.db"),
    "execution": os.getenv("EXECUTION_DB_PATH", "/data/execution.db"),
    "reputation": os.getenv("REPUTATION_DB_PATH", "/data/reputation.db"),
    "recurring": os.getenv("RECURRING_DB_PATH", "/data/recurring.db"),
    "evaluator": os.getenv("EVALUATOR_DB_PATH", "/data/evaluator.db"),
    "prospector": os.getenv("PROSPECTOR_DB_PATH", "/data/prospector.db"),
    "billing": os.getenv("BILLING_DB_PATH", "/data/billing.db"),
}

BACKUP_ROOT = os.getenv("BACKUP_DIR", "/data/backups")
MAX_BACKUPS = int(os.getenv("MAX_BACKUPS", "7"))


def backup_all():
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(BACKUP_ROOT) / ts
    backup_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for name, db_path in SERVICES.items():
        src = Path(db_path)
        if not src.exists():
            results.append({"service": name, "status": "skipped", "reason": "db not found"})
            continue

        dst = backup_dir / f"{name}.db"
        try:
            conn = sqlite3.connect(str(src))
            backup_conn = sqlite3.connect(str(dst))
            conn.backup(backup_conn)
            backup_conn.close()
            conn.close()

            size_mb = round(dst.stat().st_size / (1024 * 1024), 2)
            results.append({"service": name, "status": "ok", "size_mb": size_mb})
        except Exception as e:
            results.append({"service": name, "status": "error", "reason": str(e)})

    _prune_old_backups()

    return {"timestamp": ts, "backup_dir": str(backup_dir), "databases": results}


def _prune_old_backups():
    root = Path(BACKUP_ROOT)
    if not root.exists():
        return
    dirs = sorted([d for d in root.iterdir() if d.is_dir()], reverse=True)
    for old_dir in dirs[MAX_BACKUPS:]:
        shutil.rmtree(old_dir, ignore_errors=True)


if __name__ == "__main__":
    import json
    result = backup_all()
    print(json.dumps(result, indent=2))

    failed = [r for r in result["databases"] if r["status"] == "error"]
    sys.exit(1 if failed else 0)
