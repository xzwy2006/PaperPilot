"""core/migrations.py — Migration runner for PaperPilot."""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending SQL migrations in order."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    current = _get_version(conn)
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    for mf in migration_files:
        version = int(mf.stem.split("_")[0])
        if version <= current:
            continue
        sql = mf.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (version,)
        )
        conn.commit()


def _get_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        return row[0] or 0
    except Exception:
        return 0
