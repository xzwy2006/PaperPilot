-- PaperPilot Database Schema v1
-- Migration: 001_init

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    title TEXT,
    title_norm TEXT,
    abstract TEXT,
    authors TEXT,
    year INTEGER,
    journal TEXT,
    doi TEXT,
    pmid TEXT,
    cnki_id TEXT,
    keywords TEXT,
    fingerprint TEXT,
    raw_import_blob TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dedup_clusters (
    id TEXT PRIMARY KEY,
    confidence REAL NOT NULL,
    evidence_json TEXT,
    canonical_record_id TEXT REFERENCES records(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dedup_members (
    cluster_id TEXT NOT NULL REFERENCES dedup_clusters(id),
    record_id TEXT NOT NULL REFERENCES records(id),
    PRIMARY KEY (cluster_id, record_id)
);

CREATE TABLE IF NOT EXISTS screening_decisions (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id),
    stage TEXT NOT NULL DEFAULT 'title_abstract',
    decision TEXT NOT NULL CHECK (decision IN ('include', 'exclude', 'maybe')),
    reason_code TEXT,
    evidence_snippet TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS relevance_scores (
    record_id TEXT PRIMARY KEY REFERENCES records(id),
    score_total REAL NOT NULL DEFAULT 0,
    breakdown_json TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pdf_files (
    id TEXT PRIMARY KEY,
    record_id TEXT REFERENCES records(id),
    file_path TEXT NOT NULL,
    sha256 TEXT,
    page_count INTEGER,
    linked_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extraction_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extracted_values (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id),
    template_id TEXT REFERENCES extraction_templates(id),
    field_key TEXT NOT NULL,
    value TEXT,
    value_standardized TEXT,
    is_standardized INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    source_page INTEGER,
    source_quote TEXT,
    confidence REAL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ai_audit_logs (
    id TEXT PRIMARY KEY,
    provider TEXT,
    model TEXT,
    task_type TEXT,
    prompt_version TEXT,
    input_hash TEXT,
    output_json TEXT,
    status TEXT NOT NULL DEFAULT 'ok',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ai_suggestions (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    record_id TEXT REFERENCES records(id),
    field_key TEXT,
    suggested_value TEXT,
    confidence REAL,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extracted_value_revisions (
    id TEXT PRIMARY KEY,
    extracted_value_id TEXT NOT NULL REFERENCES extracted_values(id),
    old_value TEXT,
    new_value TEXT,
    changed_by TEXT NOT NULL DEFAULT 'manual',
    changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_records_doi ON records(doi);
CREATE INDEX IF NOT EXISTS idx_records_pmid ON records(pmid);
CREATE INDEX IF NOT EXISTS idx_records_fingerprint ON records(fingerprint);
CREATE INDEX IF NOT EXISTS idx_screening_record ON screening_decisions(record_id);
CREATE INDEX IF NOT EXISTS idx_extracted_record ON extracted_values(record_id, field_key);
CREATE INDEX IF NOT EXISTS idx_ai_suggestions_record ON ai_suggestions(record_id, status);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
