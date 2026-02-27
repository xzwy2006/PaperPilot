"""core/project.py — Project manager for PaperPilot."""
from __future__ import annotations

from pathlib import Path

from .db import get_connection
from .migrations import apply_migrations


class Project:
    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir).resolve()
        self.db_path = self.project_dir / "paperpilot.sqlite"
        self._conn = None

    @classmethod
    def create(cls, project_dir: str | Path) -> "Project":
        """Create a new project in the given directory."""
        p = cls(project_dir)
        p.project_dir.mkdir(parents=True, exist_ok=True)
        for sub in ["exports", "meta_outputs", "logs", "pdfs"]:
            (p.project_dir / sub).mkdir(exist_ok=True)
        p._init_db()
        return p

    @classmethod
    def open(cls, project_dir: str | Path) -> "Project":
        """Open an existing project."""
        p = cls(project_dir)
        if not p.db_path.exists():
            raise FileNotFoundError(f"No PaperPilot project found at {project_dir}")
        p._init_db()
        return p

    def _init_db(self):
        self._conn = get_connection(self.db_path)
        apply_migrations(self._conn)

    @property
    def conn(self):
        if self._conn is None:
            self._init_db()
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __repr__(self):
        return f"Project({self.project_dir})"
