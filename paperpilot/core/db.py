"""
core/db.py — SQLite connection helper and migration runner for PaperPilot.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Return a SQLite connection with foreign keys enabled and row_factory set."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def run_migrations(conn: sqlite3.Connection, migrations_dir: str | Path) -> None:
    """Apply all SQL migration files in order, tracking applied versions."""
    migrations_path = Path(migrations_dir)

    # Ensure schema_version table exists (bootstrapping)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT
        )
    """)
    conn.commit()

    applied = {
        row[0]
        for row in conn.execute("SELECT version FROM schema_version").fetchall()
    }

    sql_files = sorted(migrations_path.glob("*.sql"))
    for sql_file in sql_files:
        # Extract version number from filename prefix (e.g. 001_init.sql -> 1)
        try:
            version = int(sql_file.stem.split("_")[0])
        except (ValueError, IndexError):
            continue

        if version in applied:
            continue

        sql = sql_file.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )
        conn.commit()
        print(f"[db] Applied migration {sql_file.name}")


def init_db(db_path: str | Path, migrations_dir: str | Path) -> sqlite3.Connection:
    """Open (or create) a database and run all pending migrations."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    run_migrations(conn, migrations_dir)
    return conn
