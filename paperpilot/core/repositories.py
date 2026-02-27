"""core/repositories.py — CRUD repositories for PaperPilot core entities."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Optional

from .models import (
    Record, ScreeningDecision, RelevanceScore,
    PdfFile, ExtractedValue, AiSuggestion, AiAuditLog,
)


class RecordRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, record: Record) -> Record:
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO records
               (id, title, title_norm, abstract, authors, year, journal,
                doi, pmid, cnki_id, keywords, fingerprint, raw_import_blob,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (record.id, record.title, record.title_norm, record.abstract,
             record.authors, record.year, record.journal, record.doi,
             record.pmid, record.cnki_id, record.keywords, record.fingerprint,
             record.raw_import_blob, record.created_at, now)
        )
        self.conn.commit()
        return record

    def get(self, record_id: str) -> Optional[Record]:
        row = self.conn.execute(
            "SELECT * FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        return Record(**dict(row)) if row else None

    def get_by_doi(self, doi: str) -> Optional[Record]:
        row = self.conn.execute(
            "SELECT * FROM records WHERE doi = ?", (doi,)
        ).fetchone()
        return Record(**dict(row)) if row else None

    def get_by_fingerprint(self, fingerprint: str) -> Optional[Record]:
        row = self.conn.execute(
            "SELECT * FROM records WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        return Record(**dict(row)) if row else None

    def update(self, record: Record) -> Record:
        record.updated_at = datetime.utcnow().isoformat()
        self.conn.execute(
            """UPDATE records SET title=?, title_norm=?, abstract=?, authors=?,
               year=?, journal=?, doi=?, pmid=?, cnki_id=?, keywords=?,
               fingerprint=?, raw_import_blob=?, updated_at=?
               WHERE id=?""",
            (record.title, record.title_norm, record.abstract, record.authors,
             record.year, record.journal, record.doi, record.pmid,
             record.cnki_id, record.keywords, record.fingerprint,
             record.raw_import_blob, record.updated_at, record.id)
        )
        self.conn.commit()
        return record

    def list_all(self) -> list[Record]:
        rows = self.conn.execute("SELECT * FROM records ORDER BY year DESC, title").fetchall()
        return [Record(**dict(r)) for r in rows]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]


class ScreeningRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, decision: ScreeningDecision) -> ScreeningDecision:
        self.conn.execute(
            """INSERT INTO screening_decisions
               (id, record_id, stage, decision, reason_code, evidence_snippet,
                source, ts, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (decision.id, decision.record_id, decision.stage, decision.decision,
             decision.reason_code, decision.evidence_snippet, decision.source,
             decision.ts, decision.created_at)
        )
        self.conn.commit()
        return decision

    def get_latest(self, record_id: str, stage: str = "title_abstract") -> Optional[ScreeningDecision]:
        row = self.conn.execute(
            """SELECT * FROM screening_decisions
               WHERE record_id=? AND stage=?
               ORDER BY ts DESC LIMIT 1""",
            (record_id, stage)
        ).fetchone()
        return ScreeningDecision(**dict(row)) if row else None

    def get_history(self, record_id: str) -> list[ScreeningDecision]:
        rows = self.conn.execute(
            "SELECT * FROM screening_decisions WHERE record_id=? ORDER BY ts DESC",
            (record_id,)
        ).fetchall()
        return [ScreeningDecision(**dict(r)) for r in rows]


class ExtractedValueRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert(self, ev: ExtractedValue) -> ExtractedValue:
        ev.updated_at = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO extracted_values
               (id, record_id, template_id, field_key, value, value_standardized,
                is_standardized, source, source_page, source_quote, confidence,
                status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ev.id, ev.record_id, ev.template_id, ev.field_key, ev.value,
             ev.value_standardized, ev.is_standardized, ev.source, ev.source_page,
             ev.source_quote, ev.confidence, ev.status, ev.created_at, ev.updated_at)
        )
        self.conn.commit()
        return ev

    def get_for_record(self, record_id: str) -> list[ExtractedValue]:
        rows = self.conn.execute(
            "SELECT * FROM extracted_values WHERE record_id=?", (record_id,)
        ).fetchall()
        return [ExtractedValue(**dict(r)) for r in rows]


class AiSuggestionRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, suggestion: AiSuggestion) -> AiSuggestion:
        self.conn.execute(
            """INSERT INTO ai_suggestions
               (id, task_type, record_id, field_key, suggested_value,
                confidence, rationale, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (suggestion.id, suggestion.task_type, suggestion.record_id,
             suggestion.field_key, suggestion.suggested_value,
             suggestion.confidence, suggestion.rationale,
             suggestion.status, suggestion.created_at)
        )
        self.conn.commit()
        return suggestion

    def get_pending(self, task_type: Optional[str] = None) -> list[AiSuggestion]:
        if task_type:
            rows = self.conn.execute(
                "SELECT * FROM ai_suggestions WHERE status='pending' AND task_type=? ORDER BY created_at",
                (task_type,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM ai_suggestions WHERE status='pending' ORDER BY created_at"
            ).fetchall()
        return [AiSuggestion(**dict(r)) for r in rows]

    def update_status(self, suggestion_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE ai_suggestions SET status=? WHERE id=?",
            (status, suggestion_id)
        )
        self.conn.commit()


class AiAuditRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, log: AiAuditLog) -> AiAuditLog:
        self.conn.execute(
            """INSERT INTO ai_audit_logs
               (id, provider, model, task_type, prompt_version, input_hash,
                output_json, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (log.id, log.provider, log.model, log.task_type, log.prompt_version,
             log.input_hash, log.output_json, log.status, log.created_at)
        )
        self.conn.commit()
        return log
