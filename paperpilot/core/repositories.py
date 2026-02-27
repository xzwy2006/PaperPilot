"""core/repositories.py — CRUD repository stubs for PaperPilot."""
from __future__ import annotations
import sqlite3
from typing import Optional


class RecordRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, record: dict) -> str:
        self.conn.execute(
            "INSERT OR IGNORE INTO records (id, title, title_norm, abstract, authors, "
            "year, journal, doi, pmid, cnki_id, keywords, fingerprint, raw_import_blob) "
            "VALUES (:id,:title,:title_norm,:abstract,:authors,:year,:journal,"
            ":doi,:pmid,:cnki_id,:keywords,:fingerprint,:raw_import_blob)",
            record,
        )
        self.conn.commit()
        return record["id"]

    def get(self, record_id: str) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM records WHERE id=?", (record_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def update(self, record_id: str, fields: dict) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [record_id]
        self.conn.execute(f"UPDATE records SET {sets} WHERE id=?", vals)
        self.conn.commit()

    def list_all(self) -> list:
        cur = self.conn.execute("SELECT * FROM records ORDER BY year DESC")
        return [dict(r) for r in cur.fetchall()]


class ScreeningDecisionRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, decision: dict) -> str:
        self.conn.execute(
            "INSERT INTO screening_decisions (id,record_id,stage,decision,"
            "reason_code,evidence_snippet,source,ts) VALUES "
            "(:id,:record_id,:stage,:decision,:reason_code,:evidence_snippet,:source,:ts)",
            decision,
        )
        self.conn.commit()
        return decision["id"]

    def latest_for_record(self, record_id: str) -> Optional[dict]:
        cur = self.conn.execute(
            "SELECT * FROM screening_decisions WHERE record_id=? ORDER BY ts DESC LIMIT 1",
            (record_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


class ExtractedValueRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert(self, value: dict) -> str:
        self.conn.execute(
            "INSERT OR REPLACE INTO extracted_values "
            "(id,record_id,template_id,field_key,value,source,source_page,"
            "source_quote,confidence,status) VALUES "
            "(:id,:record_id,:template_id,:field_key,:value,:source,:source_page,"
            ":source_quote,:confidence,:status)",
            value,
        )
        self.conn.commit()
        return value["id"]


class AIAuditRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def log(self, entry: dict) -> str:
        self.conn.execute(
            "INSERT INTO ai_audit_logs (id,provider,model,task_type,prompt_version,"
            "input_hash,output_json,status) VALUES "
            "(:id,:provider,:model,:task_type,:prompt_version,:input_hash,:output_json,:status)",
            entry,
        )
        self.conn.commit()
        return entry["id"]
