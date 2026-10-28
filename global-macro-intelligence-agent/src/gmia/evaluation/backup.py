"""Explicit online SQLite backup. No scheduler, uploads, or overwrite of existing backups."""

import sqlite3
from contextlib import closing
from pathlib import Path


def backup_ledger(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the output before connecting, so a mistaken restore path cannot be overwritten.
    with destination.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = dst.execute("PRAGMA foreign_key_check").fetchall()
                if integrity != "ok" or foreign_keys:
                    raise ValueError("backup integrity check failed")
                counts = {t: dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                          for t in ("forecasts", "scores")}
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {"destination": str(destination), "integrity": integrity, "rows": counts}
