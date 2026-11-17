"""Backup and restore of the local Blue Cench Chat database.

A backup is a ZIP containing a consistent SQLite snapshot (made with the
SQLite online-backup API) plus a manifest.  Identity keys inside it remain
encrypted with the account password / recovery key, so a backup file alone
does not let anyone impersonate you.  Restoring is staged and applied on the
next start, because the database is in use while the app runs.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from .. import config

MANIFEST = "bluecenchchat-backup.json"
PENDING = "restore-pending.db"


def create_backup(target: Path) -> Path:
    target = Path(target)
    if target.suffix != ".nxbackup":
        target = target.with_suffix(".nxbackup")
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "bluecenchchat.db"
        src = sqlite3.connect(str(config.db_path()))
        dst = sqlite3.connect(str(snap))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap, "bluecenchchat.db")
            zf.writestr(MANIFEST, json.dumps({"app": config.APP_NAME, "version": config.APP_VERSION,
                                              "created": time.time()}))
    return target


def stage_restore(source: Path) -> None:
    with zipfile.ZipFile(source) as zf:
        names = zf.namelist()
        if MANIFEST not in names or "bluecenchchat.db" not in names:
            raise ValueError("This is not a Blue Cench Chat backup file")
        manifest = json.loads(zf.read(MANIFEST))
        if manifest.get("app") != config.APP_NAME:
            raise ValueError("This is not a Blue Cench Chat backup file")
        data = zf.read("bluecenchchat.db")
    if not data.startswith(b"SQLite format 3\x00"):
        raise ValueError("Backup is damaged")
    pending = config.data_dir() / PENDING
    pending.write_bytes(data)
    conn = sqlite3.connect(str(pending))
    try:
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    if ok != "ok" or "accounts" not in tables:
        pending.unlink(missing_ok=True)
        raise ValueError("Backup failed its integrity check")


def apply_pending_restore() -> bool:
    """Called at start-up before the database is opened."""
    pending = config.data_dir() / PENDING
    if not pending.exists():
        return False
    db = config.db_path()
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db) + suffix)
        if p.exists():
            p.replace(Path(str(db) + suffix + ".before-restore"))
    pending.replace(db)
    return True
