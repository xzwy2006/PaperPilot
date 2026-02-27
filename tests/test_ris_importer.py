"""tests/test_ris_importer.py -- Tests for the RIS importer (Phase 3.2)."""
from __future__ import annotations

import uuid
from paperpilot.core.importers.ris import parse_ris


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RPID = "550e8400-e29b-41d4-a716-446655440000"
RPF = "a" * 64  # 64-char hex fingerprint

RIS_FIXTURE = f"""\
TY  - JOUR
ID  - RPID:{RPID}
AU  - Smith, John
AU  - Doe, Jane
TI  - A Systematic Review of Awesome Things
T1  - A Systematic Review of Awesome Things
AB  - This is the abstract of an amazing study.
KW  - systematic review
KW  - meta-analysis
JO  - Journal of Awesomeness
PY  - 2023//
DO  - 10.1234/joa.2023.001
M1  - RPF:sha256:{RPF}
N1  - PaperPilot Screening Current|decision=include|stage=title_abstract|reason=TA001|score=0.95|protocol=myprotocol|updated=2024-01-15
N2  - PaperPilot Screening Log {{"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "record_id": "{RPID}", "stage": "full_text", "decision": "exclude", "reason_code": "FT002", "evidence_snippet": "animal study", "source": "manual", "ts": "2023-12-01T10:00:00", "created_at": "2023-12-01T10:00:00"}}
ER  - 

TY  - CONF
AU  - Turing, Alan
TI  - Computing Machinery and Intelligence
AB  - The imitation game abstract.
PY  - 1950
JO  - Mind
DO  - 10.1093/mind/LIX.236.433
ER  - 
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_parse_returns_two_records():
    records, decisions = parse_ris(RIS_FIXTURE)
    assert len(records) == 2


def test_standard_fields_record_one():
    records, _ = parse_ris(RIS_FIXTURE)
    rec = records[0]

    assert rec.title == "A Systematic Review of Awesome Things"
    assert rec.abstract == "This is the abstract of an amazing study."
    assert "Smith, John" in rec.authors
    assert "Doe, Jane" in rec.authors
    assert "systematic review" in rec.keywords
    assert "meta-analysis" in rec.keywords
    assert rec.journal == "Journal of Awesomeness"
    assert rec.year == 2023
    assert rec.doi == "10.1234/joa.2023.001"


def test_rpid_extracted_as_record_id():
    records, _ = parse_ris(RIS_FIXTURE)
    rec = records[0]
    assert rec.id == RPID


def test_rpf_fingerprint_extracted():
    records, _ = parse_ris(RIS_FIXTURE)
    rec = records[0]
    assert rec.fingerprint == RPF


def test_n1_decision_parsed():
    records, decisions = parse_ris(RIS_FIXTURE)
    rec = records[0]

    n1_decisions = [d for d in decisions if d.record_id == rec.id and d.stage == "title_abstract"]
    assert len(n1_decisions) == 1
    d = n1_decisions[0]
    assert d.decision == "include"
    assert d.reason_code == "TA001"
    assert d.source == "myprotocol"
    assert "0.95" in (d.evidence_snippet or "")
    assert d.ts == "2024-01-15T00:00:00"


def test_n2_history_parsed():
    records, decisions = parse_ris(RIS_FIXTURE)
    rec = records[0]

    n2_decisions = [d for d in decisions if d.record_id == rec.id and d.stage == "full_text"]
    assert len(n2_decisions) == 1
    d = n2_decisions[0]
    assert d.id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert d.decision == "exclude"
    assert d.reason_code == "FT002"
    assert d.evidence_snippet == "animal study"
    assert d.source == "manual"


def test_total_decisions_count():
    _, decisions = parse_ris(RIS_FIXTURE)
    # 1 N1 decision + 1 N2 decision from record 1; record 2 has none
    assert len(decisions) == 2


def test_second_record_no_enhanced_fields():
    records, decisions = parse_ris(RIS_FIXTURE)
    rec2 = records[1]

    assert rec2.title == "Computing Machinery and Intelligence"
    assert rec2.year == 1950
    assert rec2.doi == "10.1093/mind/LIX.236.433"
    assert rec2.fingerprint is None
    # ID is auto-generated UUID (not RPID), so not the hardcoded one
    assert rec2.id != RPID

    rec2_decisions = [d for d in decisions if d.record_id == rec2.id]
    assert len(rec2_decisions) == 0


def test_empty_ris_returns_empty_lists():
    records, decisions = parse_ris("")
    assert records == []
    assert decisions == []


def test_ris_without_enhanced_tags():
    minimal = """\
TY  - JOUR
TI  - Minimal Title
AU  - Author, A
PY  - 2020
ER  - 
"""
    records, decisions = parse_ris(minimal)
    assert len(records) == 1
    assert records[0].title == "Minimal Title"
    assert records[0].fingerprint is None
    assert decisions == []
