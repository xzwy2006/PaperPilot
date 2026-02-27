"""
paperpilot/core/screening/rules_engine.py
Local rule-based engine that generates automatic screening suggestions
for a single bibliographic record.
"""
from __future__ import annotations

import re
from typing import Any


# ─────────────────────────────────────────────────────
# Reason-code catalogue (subset used by the engine)
# ─────────────────────────────────────────────────────

_NON_HUMAN_CODE    = "TA006"   # Non-human subjects
_NON_RCT_CODE      = "TA008"   # Non-RCT design  (per taxonomy TA008)
_NON_RCT_ALT_CODE  = "TA007"   # Clearly non-human (animal / in vitro)

# Terms that strongly signal a non-human / in-vitro study
_NON_HUMAN_SIGNALS = frozenset([
    "animal", "rat", "mouse", "mice", "in vitro", "cell line",
    "zebrafish", "drosophila", "murine", "rodent", "rabbit",
    "porcine", "bovine", "canine", "primate", "monkey",
])

# Terms that strongly signal a non-RCT / excluded publication type
_NON_RCT_SIGNALS = frozenset([
    "case report", "case series", "letter to editor", "editorial",
    "commentary", "retracted", "review", "meta-analysis",
    "systematic review", "conference abstract",
])

# Strong topic keywords that raise confidence (used to resolve "maybe")
_STRONG_TOPIC_SIGNALS = frozenset([
    "randomized controlled trial", "rct", "double-blind",
    "placebo-controlled", "crossover trial",
    "randomised controlled trial",
])


# ─────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────

def _get_text(record: dict[str, Any]) -> str:
    """Concatenate title and abstract into a single lower-cased string."""
    title    = (record.get("title")    or "").lower()
    abstract = (record.get("abstract") or "").lower()
    return f"{title} {abstract}"


def _find_term(text: str, terms: frozenset[str]) -> str | None:
    """Return the first term from *terms* found as a word-boundary match in *text*."""
    for term in sorted(terms):          # deterministic order
        pattern = r"(?<![\w])" + re.escape(term) + r"(?![\w])"
        if re.search(pattern, text):
            return term
    return None


def _has_strong_topic(text: str, protocol: dict[str, Any]) -> bool:
    """Return True if *text* contains at least one design / topic keyword."""
    design_words = {w.lower() for w in protocol.get("design_allowlist", [])}
    merged = design_words | _STRONG_TOPIC_SIGNALS
    return _find_term(text, frozenset(merged)) is not None


def _get_must_exclude_terms(protocol: dict[str, Any]) -> tuple[frozenset, frozenset]:
    """Split protocol must_exclude_terms into non-human vs non-RCT sets."""
    all_must = {t.lower() for t in protocol.get("must_exclude_terms", [])}
    non_human = frozenset(all_must & _NON_HUMAN_SIGNALS)
    non_rct   = frozenset(all_must & _NON_RCT_SIGNALS)
    # anything not in either category → treat as non-RCT / generic exclusion
    remainder = frozenset(all_must - non_human - non_rct)
    non_rct   = non_rct | remainder
    return non_human, non_rct


# ─────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────

def auto_screen(record: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    """Generate an automatic screening suggestion for a single record.

    Parameters
    ----------
    record : dict
        Bibliographic record with at least ``title`` and ``abstract`` fields.
    protocol : dict
        Screening protocol as returned by
        :func:`paperpilot.core.screening.protocol.load_default_protocol`.

    Returns
    -------
    dict with keys:
        * ``decision``        – ``"include"`` | ``"exclude"`` | ``"maybe"``
        * ``reason_code``     – reason code string or ``None``
        * ``evidence_snippet`` – matched keyword fragment or ``None``
        * ``confidence``      – float in [0, 1]
    """
    text = _get_text(record)

    # ── Priority 1: must-exclude terms ───────────────────────────────────
    non_human_terms, non_rct_terms = _get_must_exclude_terms(protocol)

    hit = _find_term(text, non_human_terms)
    if hit is not None:
        return {
            "decision":         "exclude",
            "reason_code":      _NON_HUMAN_CODE,
            "evidence_snippet": hit,
            "confidence":       0.95,
        }

    hit = _find_term(text, non_rct_terms)
    if hit is not None:
        return {
            "decision":         "exclude",
            "reason_code":      _NON_RCT_ALT_CODE,
            "evidence_snippet": hit,
            "confidence":       0.90,
        }

    # ── Priority 2: soft-exclude terms (without strong topic presence) ───
    soft_terms = frozenset(
        t.lower() for t in protocol.get("soft_exclude_terms", [])
    )
    hit = _find_term(text, soft_terms)
    if hit is not None and not _has_strong_topic(text, protocol):
        return {
            "decision":         "maybe",
            "reason_code":      None,
            "evidence_snippet": hit,
            "confidence":       0.50,
        }

    # ── Priority 3: default ──────────────────────────────────────────────
    # The engine never auto-includes; human review is always required.
    return {
        "decision":         "maybe",
        "reason_code":      None,
        "evidence_snippet": None,
        "confidence":       0.40,
    }
