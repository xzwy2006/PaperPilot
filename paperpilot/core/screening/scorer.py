"""
paperpilot/core/screening/scorer.py
Relevance-scoring engine for systematic-review record triage.
"""
from __future__ import annotations

import math
import re
from typing import Any

# Maximum points per sub-component
_MAX_TITLE_KW    = 30.0
_MAX_ABSTRACT_KW = 40.0
_MAX_DESIGN      = 20.0
_MAX_RECENCY     = 10.0
_RECENCY_YEAR    = 2015


# ─────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────

def _tokenise(text: str) -> str:
    """Return lower-cased version of *text*."""
    return (text or "").lower()


def _count_hits(text: str, keywords: list[str]) -> int:
    """Count how many unique keywords (case-insensitive, word-boundary) occur in *text*."""
    hits = 0
    seen: set[str] = set()
    for kw in keywords:
        kw_low = kw.lower()
        if kw_low in seen:
            continue
        seen.add(kw_low)
        pattern = r"(?<![\w])" + re.escape(kw_low) + r"(?![\w])"
        if re.search(pattern, text):
            hits += 1
    return hits


def _keyword_score(text: str, keywords: list[str], max_score: float) -> float:
    """Return proportional score up to *max_score* based on keyword density."""
    if not keywords:
        return 0.0
    hits = _count_hits(text, keywords)
    ratio = hits / len(keywords)
    # Use a mild log curve so a few hits still give meaningful credit
    # but the first hit is rewarded more than subsequent ones.
    if hits == 0:
        return 0.0
    raw = math.log1p(hits) / math.log1p(len(keywords))
    return round(min(raw * max_score, max_score), 2)


def _design_score(title_text: str, abstract_text: str,
                  protocol: dict[str, Any]) -> float:
    """Return design-match score (0 or _MAX_DESIGN)."""
    design_words: list[str] = protocol.get("design_allowlist", [])
    combined = f"{title_text} {abstract_text}"
    hits = _count_hits(combined, design_words)
    if hits == 0:
        return 0.0
    # Partial credit: first hit = half score, any further = full score
    return _MAX_DESIGN if hits >= 2 else _MAX_DESIGN * 0.5


def _recency_score(record: dict[str, Any]) -> float:
    """Return +10 if the record year is >= _RECENCY_YEAR, else 0."""
    year_raw = record.get("year") or record.get("publication_year") or ""
    try:
        year = int(str(year_raw).strip()[:4])
    except (ValueError, TypeError):
        return 0.0
    return _MAX_RECENCY if year >= _RECENCY_YEAR else 0.0


# ─────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────

def compute_score(record: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    """Compute a relevance score (0-100) for a single bibliographic record.

    Parameters
    ----------
    record : dict
        Bibliographic record with at least ``title``, ``abstract``, and
        optionally ``year`` / ``publication_year``.
    protocol : dict
        Screening protocol as returned by
        :func:`paperpilot.core.screening.protocol.load_default_protocol`.

    Returns
    -------
    dict with keys:
        * ``score_total``  – float in [0, 100]
        * ``breakdown``    – dict with individual component scores
    """
    title_text    = _tokenise(record.get("title", ""))
    abstract_text = _tokenise(record.get("abstract", ""))

    inclusion_kws: list[str] = protocol.get("inclusion_criteria", [])

    title_kw_score    = _keyword_score(title_text,    inclusion_kws, _MAX_TITLE_KW)
    abstract_kw_score = _keyword_score(abstract_text, inclusion_kws, _MAX_ABSTRACT_KW)
    design_sc         = _design_score(title_text, abstract_text, protocol)
    recency_sc        = _recency_score(record)

    total = round(
        title_kw_score + abstract_kw_score + design_sc + recency_sc, 2
    )
    total = min(total, 100.0)

    return {
        "score_total": total,
        "breakdown": {
            "title_keyword_hits":    title_kw_score,
            "abstract_keyword_hits": abstract_kw_score,
            "design_match":          design_sc,
            "year_recency":          recency_sc,
        },
    }
