"""paperpilot/core/importers/ris.py -- RIS format importer for PaperPilot.

Parses standard RIS tags and PaperPilot-enhanced fields (RPID, RPF, N1/N2).
Returns (records, decisions) tuple.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date
from typing import Optional

from paperpilot.core.models import Record, ScreeningDecision


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"^([A-Z][A-Z0-9])  - (.*)$")

# RPID pattern embedded in ID tag
_RPID_RE = re.compile(r"RPID:([0-9a-f-]{32,36})", re.IGNORECASE)
# RPF fingerprint pattern embedded in M1 tag
_RPF_RE = re.compile(r"RPF:sha256:([0-9a-fA-F]{64})", re.IGNORECASE)

# N1 current-state prefix
_N1_PREFIX = "PaperPilot Screening Current|"
# N2 history prefix
_N2_PREFIX = "PaperPilot Screening Log "


def _parse_year(raw: str) -> Optional[int]:
    """Extract 4-digit year from PY/Y1 field (may be 'YYYY//' or 'YYYY')."""
    m = re.search(r"\b(\d{4})\b", raw)
    return int(m.group(1)) if m else None


def _parse_pipe_fields(segment: str) -> dict:
    """Parse 'key=value|key=value|...' pipe-separated fields."""
    result = {}
    for part in segment.split("|"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            result[k.strip()] = v.strip()
    return result


def _parse_n1_decision(value: str, record_id: str) -> Optional[ScreeningDecision]:
    """Parse N1 'PaperPilot Screening Current|...' into a ScreeningDecision."""
    if not value.startswith(_N1_PREFIX):
        return None
    segment = value[len(_N1_PREFIX):]
    fields = _parse_pipe_fields(segment)

    decision_val = fields.get("decision", "")
    if not decision_val:
        return None

    ts_val = fields.get("updated", date.today().isoformat())
    # Normalise to ISO datetime if only date given
    if re.match(r"^\d{4}-\d{2}-\d{2}$", ts_val):
        ts_val = ts_val + "T00:00:00"

    score_raw = fields.get("score")
    evidence = f"score={score_raw}" if score_raw else None

    return ScreeningDecision(
        id=str(uuid.uuid4()),
        record_id=record_id,
        stage=fields.get("stage", "title_abstract"),
        decision=decision_val,
        reason_code=fields.get("reason") or None,
        evidence_snippet=evidence,
        source=fields.get("protocol", "manual"),
        ts=ts_val,
        created_at=ts_val,
    )


def _parse_n2_decision(value: str, record_id: str) -> Optional[ScreeningDecision]:
    """Parse N2 'PaperPilot Screening Log {...json...}' into a ScreeningDecision."""
    if not value.startswith(_N2_PREFIX):
        return None
    json_part = value[len(_N2_PREFIX):]
    # Find the first '{' and last '}'
    start = json_part.find("{")
    end = json_part.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(json_part[start : end + 1])
    except json.JSONDecodeError:
        return None

    decision_val = data.get("decision", "")
    if not decision_val:
        return None

    ts_val = data.get("ts") or data.get("created_at") or date.today().isoformat()

    return ScreeningDecision(
        id=data.get("id", str(uuid.uuid4())),
        record_id=record_id,
        stage=data.get("stage", "title_abstract"),
        decision=decision_val,
        reason_code=data.get("reason_code") or None,
        evidence_snippet=data.get("evidence_snippet") or None,
        source=data.get("source", "manual"),
        ts=ts_val,
        created_at=data.get("created_at", ts_val),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_ris(text: str) -> tuple[list[Record], list[ScreeningDecision]]:
    """Parse RIS-formatted text and return (records, decisions).

    Handles standard tags plus PaperPilot-enhanced fields:
      - ID  tag with ``RPID:<uuid>``  → record.id
      - M1  tag with ``RPF:sha256:<hex>`` → record.fingerprint
      - N1  tag: current screening state   → ScreeningDecision (source='n1')
      - N2  tag: screening history entry   → ScreeningDecision (source from JSON)

    Args:
        text: Full content of a .ris file as a string.

    Returns:
        A 2-tuple ``(records, decisions)`` where each decision is linked to
        its record via ``decision.record_id``.
    """
    records: list[Record] = []
    decisions: list[ScreeningDecision] = []

    # Split into individual reference blocks on ER  -
    blocks = re.split(r"^ER\s+-.*$", text, flags=re.MULTILINE)

    for block in blocks:
        lines = block.splitlines()

        # Collect raw tag → [values] for this block
        tags: dict[str, list[str]] = {}
        for line in lines:
            m = _TAG_RE.match(line)
            if m:
                tag, val = m.group(1), m.group(2).strip()
                tags.setdefault(tag, []).append(val)

        # Skip empty blocks (no TY found and no meaningful content)
        if not tags:
            continue

        # ---- Standard fields ------------------------------------------------
        title = (
            tags.get("TI", tags.get("T1", [None]))[0]
        )
        abstract = tags.get("AB", [None])[0]
        authors = "; ".join(tags.get("AU", []))
        keywords = "; ".join(tags.get("KW", []))
        journal = (
            tags.get("JO", tags.get("T2", [None]))[0]
        )

        year_raw = (tags.get("PY") or tags.get("Y1") or [None])[0]
        year = _parse_year(year_raw) if year_raw else None

        doi = tags.get("DO", [None])[0]

        # ---- Enhanced fields ------------------------------------------------
        record_id: Optional[str] = None
        fingerprint: Optional[str] = None

        id_vals = tags.get("ID", [])
        for id_val in id_vals:
            m = _RPID_RE.search(id_val)
            if m:
                record_id = m.group(1).lower()
                break

        m1_vals = tags.get("M1", [])
        for m1_val in m1_vals:
            m = _RPF_RE.search(m1_val)
            if m:
                fingerprint = m.group(1).lower()
                break

        # Build Record
        rec_kwargs = dict(
            title=title or None,
            abstract=abstract or None,
            authors=authors or None,
            keywords=keywords or None,
            journal=journal or None,
            year=year,
            doi=doi or None,
            fingerprint=fingerprint,
        )
        if record_id:
            rec_kwargs["id"] = record_id

        rec = Record(**rec_kwargs)
        records.append(rec)

        # ---- Decisions from N1 (current state) ------------------------------
        for n1_val in tags.get("N1", []):
            d = _parse_n1_decision(n1_val, rec.id)
            if d:
                decisions.append(d)

        # ---- Decisions from N2 (history entries) ----------------------------
        for n2_val in tags.get("N2", []):
            d = _parse_n2_decision(n2_val, rec.id)
            if d:
                decisions.append(d)

    return records, decisions
