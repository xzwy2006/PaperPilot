"""
Deduplication clustering engine for PaperPilot.

Implements three matching rules:
  D1 — Exact ID match (DOI / PMID / CNKI_ID), confidence = 1.0
  D2 — Title + year + author,                  confidence = 0.95
  D3 — Fuzzy title + author,                   confidence = 0.85

Uses Union-Find for efficient transitive clustering.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from rapidfuzz import fuzz

from .normalize import normalize_author, normalize_doi


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class DedupCluster:
    """A group of records identified as potential duplicates."""
    id: str                   # UUID for this cluster
    confidence: float         # Highest confidence among all pairwise matches
    evidence_json: str        # JSON string with match rule and field scores
    canonical_record_id: str  # ID of the most information-rich record
    member_ids: list[str]     # All record IDs in this cluster


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_record(record: dict) -> int:
    """
    Return an information-richness score for canonical record selection.
    Priority: has DOI > has abstract > more non-empty fields > earlier import.
    """
    score = 0
    if record.get("doi"):
        score += 100
    if record.get("abstract"):
        score += 50
    # Count non-empty fields
    score += sum(1 for v in record.values() if v not in (None, "", [], {}))
    return score


def _get_first_author_norm(record: dict) -> str:
    """Return the normalized last name of the first author."""
    authors = record.get("authors", "")
    if isinstance(authors, list):
        authors = "; ".join(str(a) for a in authors) if authors else ""
    return normalize_author(str(authors) if authors else "")


def _year_compatible(r1: dict, r2: dict) -> bool:
    """Return True if year difference <= 1, or if either year is missing."""
    y1 = r1.get("year")
    y2 = r2.get("year")
    if y1 is None or y2 is None or y1 == "" or y2 == "":
        return True
    try:
        return abs(int(y1) - int(y2)) <= 1
    except (ValueError, TypeError):
        return True


def _author_sim(a1: str, a2: str) -> float:
    """Return fuzz.ratio similarity [0, 1]; 1.0 if either is empty."""
    if not a1 or not a2:
        return 1.0
    return fuzz.ratio(a1, a2) / 100.0


# ---------------------------------------------------------------------------
# Union-Find with confidence/evidence propagation
# ---------------------------------------------------------------------------

class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n
        self.confidence: list[float] = [0.0] * n
        self.evidence: list[dict] = [{} for _ in range(n)]

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int, confidence: float, evidence: dict) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            # Already same cluster — update to better evidence if confidence is higher
            if confidence > self.confidence[ra]:
                self.confidence[ra] = confidence
                self.evidence[ra] = evidence
            return
        # Union by rank
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        # Keep best confidence/evidence
        if confidence >= max(self.confidence[ra], self.confidence[rb]):
            self.confidence[ra] = confidence
            self.evidence[ra] = evidence
        elif self.confidence[ra] >= self.confidence[rb]:
            pass  # ra already has best
        else:
            self.confidence[ra] = self.confidence[rb]
            self.evidence[ra] = self.evidence[rb]


# ---------------------------------------------------------------------------
# Main clustering function
# ---------------------------------------------------------------------------

def cluster_records(records: list[dict]) -> list[DedupCluster]:
    """
    Cluster *records* into groups of potential duplicates.

    Args:
        records: List of record dicts.  Required keys: ``id``.  Optional but
                 used: ``title_norm``, ``year``, ``authors``, ``doi``,
                 ``pmid``, ``cnki_id``, ``abstract``.

    Returns:
        List of :class:`DedupCluster` objects (only clusters with ≥ 2 members).
    """
    n = len(records)
    if n == 0:
        return []

    records_by_id: dict[str, dict] = {r["id"]: r for r in records}
    uf = _UnionFind(n)

    # ------------------------------------------------------------------
    # Build lookup maps for D1 (exact ID match)
    # ------------------------------------------------------------------
    doi_map: dict[str, list[int]] = {}
    pmid_map: dict[str, list[int]] = {}
    cnki_map: dict[str, list[int]] = {}

    for i, r in enumerate(records):
        doi = normalize_doi(r.get("doi", "") or "")
        if doi:
            doi_map.setdefault(doi, []).append(i)

        pmid = str(r.get("pmid", "") or "").strip()
        if pmid:
            pmid_map.setdefault(pmid, []).append(i)

        cnki_id = str(r.get("cnki_id", "") or "").strip()
        if cnki_id:
            cnki_map.setdefault(cnki_id, []).append(i)

    # ------------------------------------------------------------------
    # D1 — Exact ID match (confidence = 1.0)
    # ------------------------------------------------------------------
    for id_map, field_name in [
        (doi_map, "doi"),
        (pmid_map, "pmid"),
        (cnki_map, "cnki_id"),
    ]:
        for key, indices in id_map.items():
            for j in range(1, len(indices)):
                evidence = {
                    "rule": "D1",
                    "field": field_name,
                    "matched_value": key,
                    "confidence": 1.0,
                }
                uf.union(indices[0], indices[j], 1.0, evidence)

    # ------------------------------------------------------------------
    # Precompute per-record title norms and author norms
    # ------------------------------------------------------------------
    title_norms: list[str] = [r.get("title_norm", "") or "" for r in records]
    author_norms: list[str] = [_get_first_author_norm(r) for r in records]

    # ------------------------------------------------------------------
    # D2 / D3 — pairwise comparisons
    # ------------------------------------------------------------------
    for i in range(n):
        t1 = title_norms[i]
        if not t1:
            continue
        a1 = author_norms[i]

        for j in range(i + 1, n):
            if uf.find(i) == uf.find(j):
                continue  # Already in same cluster

            t2 = title_norms[j]
            if not t2:
                continue

            a2 = author_norms[j]

            # -- D2: exact title + year within 1 + author similarity >= 0.80 --
            if t1 == t2 and _year_compatible(records[i], records[j]):
                sim_a = _author_sim(a1, a2)
                if sim_a >= 0.80:
                    evidence = {
                        "rule": "D2",
                        "title_exact_match": True,
                        "year_compatible": True,
                        "author_similarity": round(sim_a, 4),
                        "confidence": 0.95,
                    }
                    uf.union(i, j, 0.95, evidence)
                    continue  # Don't also try D3 for this pair

            # -- D3: fuzzy title >= 0.92 + author similarity >= 0.70 ----------
            title_sim = fuzz.token_sort_ratio(t1, t2) / 100.0
            if title_sim >= 0.92:
                sim_a = _author_sim(a1, a2)
                if sim_a >= 0.70:
                    evidence = {
                        "rule": "D3",
                        "title_similarity": round(title_sim, 4),
                        "author_similarity": round(sim_a, 4),
                        "confidence": 0.85,
                    }
                    uf.union(i, j, 0.85, evidence)

    # ------------------------------------------------------------------
    # Collect groups
    # ------------------------------------------------------------------
    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)

    # ------------------------------------------------------------------
    # Build DedupCluster objects (only multi-member groups)
    # ------------------------------------------------------------------
    result: list[DedupCluster] = []
    for root, indices in groups.items():
        if len(indices) < 2:
            continue

        member_ids = [records[i]["id"] for i in indices]
        confidence = uf.confidence[root]
        evidence = uf.evidence[root]

        # Canonical: highest-scoring record
        members = [records[i] for i in indices]
        canonical = max(members, key=_score_record)

        result.append(DedupCluster(
            id=str(uuid.uuid4()),
            confidence=confidence,
            evidence_json=json.dumps(evidence, ensure_ascii=False),
            canonical_record_id=canonical["id"],
            member_ids=member_ids,
        ))

    return result
