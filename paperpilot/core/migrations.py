"""
core/migrations.py — Migration utilities (thin wrapper around db.run_migrations).
"""
from __future__ import annotations

from pathlib import Path

from paperpilot.core.db import run_migrations, get_connection


DEFAULT_MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"


def apply(db_path: str | Path, migrations_dir: str | Path | None = None) -> None:
    """Apply pending migrations to the given database path."""
    if migrations_dir is None:
        migrations_dir = DEFAULT_MIGRATIONS_DIR
    conn = get_connection(db_path)
    try:
        run_migrations(conn, migrations_dir)
    finally:
        conn.close()
