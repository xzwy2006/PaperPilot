"""core/db.py — SQLite connection manager for PaperPilot."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


_connections: dict[str, sqlite3.Connection] = {}


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Get or create a SQLite connection for the given path."""
    key = str(db_path)
    if key not in _connections or _is_closed(_connections[key]):
        conn = sqlite3.connect(key, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _connections[key] = conn
    return _connections[key]


def close_connection(db_path: str | Path) -> None:
    key = str(db_path)
    if key in _connections:
        try:
            _connections[key].close()
        except Exception:
            pass
        del _connections[key]


def _is_closed(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1")
        return False
    except Exception:
        return True
