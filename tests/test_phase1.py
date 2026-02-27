"""Tests for Phase 1 — DB, migrations, repositories."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from paperpilot.core.project import Project
from paperpilot.core.models import Record, ScreeningDecision, ExtractedValue
from paperpilot.core.repositories import (
    RecordRepository, ScreeningRepository, ExtractedValueRepository
)


def test_project_create_opens_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Project.create(tmpdir)
        assert project.db_path.exists()
        # Check subdirs created
        for sub in ["exports", "meta_outputs", "logs", "pdfs"]:
            assert (project.project_dir / sub).exists()
        project.close()


def test_migrations_apply():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Project.create(tmpdir)
        conn = project.conn
        # Verify all tables exist
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        expected = {
            "records", "dedup_clusters", "dedup_members", "screening_decisions",
            "relevance_scores", "pdf_files", "extraction_templates",
            "extracted_values", "ai_audit_logs", "ai_suggestions",
            "extracted_value_revisions", "schema_version"
        }
        assert expected <= tables, f"Missing tables: {expected - tables}"
        project.close()


def test_record_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Project.create(tmpdir)
        repo = RecordRepository(project.conn)

        # Create
        rec = Record(title="Test Paper", year=2024, doi="10.1234/test")
        repo.insert(rec)

        # Fetch
        fetched = repo.get(rec.id)
        assert fetched is not None
        assert fetched.title == "Test Paper"
        assert fetched.doi == "10.1234/test"

        # Update
        fetched.title = "Updated Paper"
        repo.update(fetched)
        updated = repo.get(rec.id)
        assert updated.title == "Updated Paper"

        # By DOI
        by_doi = repo.get_by_doi("10.1234/test")
        assert by_doi is not None
        assert by_doi.id == rec.id

        project.close()


def test_screening_decision_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Project.create(tmpdir)
        rec_repo = RecordRepository(project.conn)
        s_repo = ScreeningRepository(project.conn)

        rec = Record(title="Screening Test", year=2023)
        rec_repo.insert(rec)

        decision = ScreeningDecision(
            record_id=rec.id, decision="exclude",
            reason_code="TA006", evidence_snippet="animal study"
        )
        s_repo.insert(decision)

        latest = s_repo.get_latest(rec.id)
        assert latest is not None
        assert latest.decision == "exclude"
        assert latest.reason_code == "TA006"

        history = s_repo.get_history(rec.id)
        assert len(history) >= 1

        project.close()


def test_extracted_value_upsert():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Project.create(tmpdir)
        rec_repo = RecordRepository(project.conn)
        ev_repo = ExtractedValueRepository(project.conn)

        rec = Record(title="Extraction Test", year=2022)
        rec_repo.insert(rec)

        ev = ExtractedValue(
            record_id=rec.id, field_key="events_t",
            value="15", source="manual", status="accepted"
        )
        ev_repo.upsert(ev)

        values = ev_repo.get_for_record(rec.id)
        assert len(values) == 1
        assert values[0].value == "15"

        project.close()
