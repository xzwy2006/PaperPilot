"""
core/models.py — Pydantic models for PaperPilot core entities.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Record(BaseModel):
    """A bibliographic record imported from any source."""

    id: str
    title: Optional[str] = None
    title_norm: Optional[str] = None
    abstract: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    cnki_id: Optional[str] = None
    keywords: Optional[str] = None
    fingerprint: Optional[str] = None
    raw_import_blob: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ScreeningDecision(BaseModel):
    """A screening decision (title/abstract or full-text stage)."""

    id: str
    record_id: str
    stage: str  # 'title_abstract' | 'full_text'
    decision: str  # 'include' | 'exclude' | 'maybe'
    reason_code: Optional[str] = None  # TA001..TA011
    evidence_snippet: Optional[str] = None
    source: str = "manual"  # 'manual' | 'ai'
    ts: Optional[str] = None
    created_at: Optional[str] = None


class PDFFile(BaseModel):
    """A PDF file linked to a record."""

    id: str
    record_id: str
    file_path: str
    sha256: Optional[str] = None
    page_count: Optional[int] = None
    linked_at: Optional[str] = None


class ExtractedValue(BaseModel):
    """An extracted data value from a record."""

    id: str
    record_id: str
    template_id: str
    field_key: str
    value: Optional[str] = None
    value_standardized: Optional[str] = None
    is_standardized: int = 0
    source: Optional[str] = None  # 'manual' | 'ai' | 'import'
    source_page: Optional[int] = None
    source_quote: Optional[str] = None
    confidence: Optional[float] = None
    status: str = "pending"  # 'pending' | 'confirmed' | 'rejected'
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AIAuditLog(BaseModel):
    """Audit log entry for every AI API call."""

    id: str
    provider: Optional[str] = None
    model: Optional[str] = None
    task_type: Optional[str] = None
    prompt_version: Optional[str] = None
    input_hash: Optional[str] = None
    output_json: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[str] = None


class AISuggestion(BaseModel):
    """An AI-generated suggestion awaiting human review."""

    id: str
    task_type: Optional[str] = None
    record_id: Optional[str] = None
    field_key: Optional[str] = None
    suggested_value: Optional[str] = None
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    status: str = "pending"  # 'pending' | 'accepted' | 'rejected'
    created_at: Optional[str] = None
