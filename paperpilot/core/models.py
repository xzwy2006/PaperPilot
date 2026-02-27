"""core/models.py -- Pydantic models for PaperPilot core entities."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


def _uuid() -> str:
    return str(uuid.uuid4())


class Record(BaseModel):
    id: str = Field(default_factory=_uuid)
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
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ScreeningDecision(BaseModel):
    id: str = Field(default_factory=_uuid)
    record_id: str
    stage: str = "title_abstract"
    decision: str  # include | exclude | maybe
    reason_code: Optional[str] = None
    evidence_snippet: Optional[str] = None
    source: str = "manual"
    ts: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class RelevanceScore(BaseModel):
    record_id: str
    score_total: float = 0.0
    breakdown_json: Optional[str] = None
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class PdfFile(BaseModel):
    id: str = Field(default_factory=_uuid)
    record_id: Optional[str] = None
    file_path: str
    sha256: Optional[str] = None
    page_count: Optional[int] = None
    linked_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ExtractedValue(BaseModel):
    id: str = Field(default_factory=_uuid)
    record_id: str
    template_id: Optional[str] = None
    field_key: str
    value: Optional[str] = None
    value_standardized: Optional[str] = None
    is_standardized: int = 0
    source: str = "manual"
    source_page: Optional[int] = None
    source_quote: Optional[str] = None
    confidence: Optional[float] = None
    status: str = "pending"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class AiSuggestion(BaseModel):
    id: str = Field(default_factory=_uuid)
    task_type: str
    record_id: Optional[str] = None
    field_key: Optional[str] = None
    suggested_value: Optional[str] = None
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    status: str = "pending"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class AiAuditLog(BaseModel):
    id: str = Field(default_factory=_uuid)
    provider: Optional[str] = None
    model: Optional[str] = None
    task_type: Optional[str] = None
    prompt_version: Optional[str] = None
    input_hash: Optional[str] = None
    output_json: Optional[str] = None
    status: str = "ok"
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
