"""
Tests for paperpilot.core.dedup — normalize.py and matching.py.

Covers:
  * normalize_title / normalize_author / normalize_doi
  * D1 rule (exact ID: DOI, PMID)
  * D2 rule (exact title + year + author similarity)
  * D3 rule (fuzzy title + author similarity)
  * Canonical record selection (doi preferred > abstract preferred)
  * evidence_json validity and required fields
"""
from __future__ import annotations

import json
import unittest
import unicodedata
from unittest.mock import patch

from paperpilot.core.dedup.normalize import normalize_title, normalize_author, normalize_doi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    rec_id: str,
    title: str = "",
    year: int | None = 2020,
    authors: str = "",
    doi: str = "",
    pmid: str = "",
    abstract: str = "",
    fingerprint: str = "",
    cnki_id: str = "",
) -> dict:
    """Build a minimal record dict that matches the expected schema."""
    return {
        "id": rec_id,
        "title": title,
        "title_norm": normalize_title(title),
        "year": year,
        "authors": authors,
        "doi": doi,
        "pmid": pmid,
        "abstract": abstract,
        "fingerprint": fingerprint,
        "cnki_id": cnki_id,
    }


# ---------------------------------------------------------------------------
# Conditionally import cluster_records with rapidfuzz mock fallback
# ---------------------------------------------------------------------------

try:
    from rapidfuzz import fuzz as _real_fuzz
    _RAPIDFUZZ_AVAILABLE = True
except ImportError:
    _RAPIDFUZZ_AVAILABLE = False


def _cluster(records: list[dict]):
    """Import and call cluster_records, mocking rapidfuzz if unavailable."""
    if _RAPIDFUZZ_AVAILABLE:
        from paperpilot.core.dedup.matching import cluster_records
        return cluster_records(records)

    # rapidfuzz not installed — patch it before importing matching
    mock_fuzz = unittest.mock.MagicMock()
    # ratio: character-level similarity
    mock_fuzz.ratio = lambda a, b: 100.0 if a == b else 0.0
    # token_sort_ratio: used for D3 fuzzy matching
    mock_fuzz.token_sort_ratio = lambda a, b: 100.0 if a == b else 0.0

    import sys
    fake_rapidfuzz = unittest.mock.MagicMock()
    fake_rapidfuzz.fuzz = mock_fuzz

    with patch.dict(sys.modules, {"rapidfuzz": fake_rapidfuzz,
                                   "rapidfuzz.fuzz": mock_fuzz}):
        # Force reimport
        if "paperpilot.core.dedup.matching" in sys.modules:
            del sys.modules["paperpilot.core.dedup.matching"]
        from paperpilot.core.dedup.matching import cluster_records
        result = cluster_records(records)

    return result


# ===========================================================================
# 1. normalize.py
# ===========================================================================

class TestNormalize(unittest.TestCase):

    # -- normalize_title ------------------------------------------------------

    def test_title_lowercase(self):
        """Mixed-case input should be fully lowercased."""
        result = normalize_title("Hello WORLD")
        self.assertEqual(result, "hello world")

    def test_title_punctuation(self):
        """Punctuation (non-word chars) should be removed / replaced by space."""
        result = normalize_title("Hello, World!")
        self.assertEqual(result, "hello world")

    def test_title_nfkc(self):
        """Unicode NFKC normalisation should be applied before lowercasing."""
        # LATIN SMALL LETTER A WITH RING ABOVE (U+00E5) stays the same under
        # NFKC but full-width letters (U+FF21…) should be normalised.
        full_width_A = "\uFF21"  # Fullwidth Latin Capital Letter A → "A" after NFKC
        result = normalize_title(full_width_A)
        nfkc_expected = unicodedata.normalize("NFKC", full_width_A).lower()
        # After removing punctuation and collapsing spaces
        self.assertEqual(result, nfkc_expected.strip())

    def test_title_fold_spaces(self):
        """Multiple consecutive spaces (or tab/newline) should collapse to one."""
        result = normalize_title("deep   learning\n for  nlp")
        self.assertEqual(result, "deep learning for nlp")

    def test_title_empty(self):
        """Empty string should return empty string."""
        self.assertEqual(normalize_title(""), "")

    # -- normalize_author -----------------------------------------------------

    def test_author_first_only(self):
        """Only the last name of the first (semicolon-delimited) author is returned."""
        result = normalize_author("Smith, John; Jones, Bob")
        self.assertEqual(result, "smith")

    def test_author_first_last_format(self):
        """'First Last' format — last token taken as last name."""
        result = normalize_author("John Smith")
        self.assertEqual(result, "smith")

    def test_author_empty(self):
        """Empty string should return empty string."""
        self.assertEqual(normalize_author(""), "")

    def test_author_and_separated(self):
        """' and '-separated list: only first author's last name returned."""
        result = normalize_author("Alice Brown and Charlie Davis")
        self.assertEqual(result, "brown")

    # -- normalize_doi --------------------------------------------------------

    def test_doi_lowercase(self):
        """DOIs should be lowercased and stripped."""
        result = normalize_doi("10.1000/XYZ")
        self.assertEqual(result, "10.1000/xyz")

    def test_doi_strip_whitespace(self):
        """Leading/trailing whitespace should be removed."""
        result = normalize_doi("  10.1000/abc  ")
        self.assertEqual(result, "10.1000/abc")

    def test_doi_empty(self):
        """Empty DOI should return empty string."""
        self.assertEqual(normalize_doi(""), "")


# ===========================================================================
# 2. matching.py — D1 rule (exact ID match)
# ===========================================================================

class TestD1Rule(unittest.TestCase):

    def test_doi_match(self):
        """Two records sharing the same DOI → confidence = 1.0, same cluster."""
        r1 = _make_record("r1", title="Paper A", doi="10.1000/xyz", authors="Smith, John")
        r2 = _make_record("r2", title="Paper A different", doi="10.1000/xyz", authors="Smith, J")
        clusters = _cluster([r1, r2])
        self.assertEqual(len(clusters), 1)
        c = clusters[0]
        self.assertAlmostEqual(c.confidence, 1.0)
        self.assertIn("r1", c.member_ids)
        self.assertIn("r2", c.member_ids)

    def test_pmid_match(self):
        """Two records sharing the same PMID → confidence = 1.0."""
        r1 = _make_record("r1", title="Paper B", pmid="12345678")
        r2 = _make_record("r2", title="Paper B alt", pmid="12345678")
        clusters = _cluster([r1, r2])
        self.assertEqual(len(clusters), 1)
        self.assertAlmostEqual(clusters[0].confidence, 1.0)

    def test_doi_different(self):
        """Records with different non-empty DOIs should NOT be clustered (by D1)."""
        r1 = _make_record("r1", title="Same Title", doi="10.1000/aaa")
        r2 = _make_record("r2", title="Same Title", doi="10.1000/bbb")
        # title_norm identical → D2 might still fire; force year diff to prevent it
        r1["year"] = 2020
        r2["year"] = 2023
        clusters = _cluster([r1, r2])
        # Should not be in same cluster
        member_sets = [set(c.member_ids) for c in clusters]
        self.assertFalse(
            any({"r1", "r2"} <= s for s in member_sets),
            "Records with different DOIs should not cluster (different year prevents D2/D3)",
        )

    def test_empty_doi_no_match(self):
        """Records with empty DOI should NOT trigger D1 clustering."""
        r1 = _make_record("r1", title="Paper C", doi="")
        r2 = _make_record("r2", title="Paper D", doi="")
        # Different titles → also won't match D2/D3
        clusters = _cluster([r1, r2])
        member_sets = [set(c.member_ids) for c in clusters]
        self.assertFalse(any({"r1", "r2"} <= s for s in member_sets))


# ===========================================================================
# 3. matching.py — D2 rule
# ===========================================================================

class TestD2Rule(unittest.TestCase):

    def test_exact_title_same_year_same_author(self):
        """Identical normalised title + same year + similar author → confidence = 0.95."""
        title = "deep learning for clinical text mining"
        r1 = _make_record("r1", title=title, year=2021, authors="Smith, John")
        r2 = _make_record("r2", title=title, year=2021, authors="Smith, J")
        clusters = _cluster([r1, r2])
        self.assertEqual(len(clusters), 1)
        self.assertAlmostEqual(clusters[0].confidence, 0.95)

    def test_year_diff_2(self):
        """Year difference of 2 should prevent D2 clustering (tolerance is ≤ 1)."""
        title = "neural network for text classification"
        r1 = _make_record("r1", title=title, year=2019, authors="Jones, Bob")
        r2 = _make_record("r2", title=title, year=2021, authors="Jones, B")
        clusters = _cluster([r1, r2])
        member_sets = [set(c.member_ids) for c in clusters]
        self.assertFalse(any({"r1", "r2"} <= s for s in member_sets))

    def test_low_author_similarity(self):
        """Author similarity < 0.8 on an exact title match should block D2."""
        title = "systematic review of machine learning methods"
        r1 = _make_record("r1", title=title, year=2020, authors="Smith, Alice")
        r2 = _make_record("r2", title=title, year=2020, authors="Zhao, Xiaowei")
        clusters = _cluster([r1, r2])
        member_sets = [set(c.member_ids) for c in clusters]
        # These authors are very different; should not cluster via D2
        # (D3 also requires author_sim >= 0.70)
        self.assertFalse(any({"r1", "r2"} <= s for s in member_sets))


# ===========================================================================
# 4. matching.py — D3 rule
# ===========================================================================

class TestD3Rule(unittest.TestCase):

    def test_fuzzy_title_match(self):
        """
        Title fuzzy ≥ 0.92 + author similarity ≥ 0.70 → cluster with confidence = 0.85.

        We mock rapidfuzz to return a controlled high similarity value so the
        test is not sensitive to the installed library version.
        """
        title_a = "machine learning in clinical decision support systems"
        title_b = "machine learning in clinical decision-support systems"
        r1 = _make_record("r1", title=title_a, year=2022, authors="Brown, Carol")
        r2 = _make_record("r2", title=title_b, year=2022, authors="Brown, C")

        if _RAPIDFUZZ_AVAILABLE:
            from rapidfuzz import fuzz
            sim = fuzz.token_sort_ratio(r1["title_norm"], r2["title_norm"]) / 100.0
            if sim < 0.92:
                self.skipTest(
                    f"Real rapidfuzz similarity {sim:.3f} < 0.92; titles may differ too much"
                )
            clusters = _cluster([r1, r2])
        else:
            # Patch: token_sort_ratio returns 0.94 (× 100 = 94), ratio 1.0 for same → same author
            import sys, unittest.mock as mock_module
            mock_fuzz = mock_module.MagicMock()
            mock_fuzz.ratio = lambda a, b: 100.0  # author sim = 1.0
            mock_fuzz.token_sort_ratio = lambda a, b: 94.0  # title sim = 0.94
            fake_rf = mock_module.MagicMock()
            fake_rf.fuzz = mock_fuzz
            with patch.dict(sys.modules, {"rapidfuzz": fake_rf, "rapidfuzz.fuzz": mock_fuzz}):
                if "paperpilot.core.dedup.matching" in sys.modules:
                    del sys.modules["paperpilot.core.dedup.matching"]
                from paperpilot.core.dedup.matching import cluster_records
                clusters = cluster_records([r1, r2])

        self.assertEqual(len(clusters), 1)
        self.assertAlmostEqual(clusters[0].confidence, 0.85)

    def test_low_title_similarity(self):
        """Title fuzzy < 0.92 should NOT produce a D3 cluster."""
        title_a = "deep learning for image recognition"
        title_b = "random forest for clinical prediction"
        r1 = _make_record("r1", title=title_a, year=2020, authors="Lee, David")
        r2 = _make_record("r2", title=title_b, year=2020, authors="Lee, D")

        if _RAPIDFUZZ_AVAILABLE:
            clusters = _cluster([r1, r2])
        else:
            import sys, unittest.mock as mock_module
            mock_fuzz = mock_module.MagicMock()
            mock_fuzz.ratio = lambda a, b: 100.0
            mock_fuzz.token_sort_ratio = lambda a, b: 50.0  # low sim
            fake_rf = mock_module.MagicMock()
            fake_rf.fuzz = mock_fuzz
            with patch.dict(sys.modules, {"rapidfuzz": fake_rf, "rapidfuzz.fuzz": mock_fuzz}):
                if "paperpilot.core.dedup.matching" in sys.modules:
                    del sys.modules["paperpilot.core.dedup.matching"]
                from paperpilot.core.dedup.matching import cluster_records
                clusters = cluster_records([r1, r2])

        member_sets = [set(c.member_ids) for c in clusters]
        self.assertFalse(any({"r1", "r2"} <= s for s in member_sets))


# ===========================================================================
# 5. Canonical record selection
# ===========================================================================

class TestCanonical(unittest.TestCase):

    def test_doi_preferred(self):
        """Among cluster members, the record with a DOI should be canonical."""
        doi = "10.9999/test"
        title = "canonical selection test doi"
        r1 = _make_record("r1", title=title, year=2021, authors="Xu, Li", doi=doi)
        r2 = _make_record("r2", title=title, year=2021, authors="Xu, L", doi="")
        clusters = _cluster([r1, r2])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].canonical_record_id, "r1")

    def test_abstract_preferred(self):
        """When no record has a DOI, the one with an abstract should be canonical."""
        title = "canonical selection test abstract"
        r1 = _make_record("r1", title=title, year=2021, authors="Wang, Fang",
                           doi="", abstract="")
        r2 = _make_record("r2", title=title, year=2021, authors="Wang, F",
                           doi="", abstract="This paper investigates…")
        clusters = _cluster([r1, r2])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].canonical_record_id, "r2")


# ===========================================================================
# 6. evidence_json
# ===========================================================================

class TestEvidenceJson(unittest.TestCase):

    def _get_cluster_with_doi(self):
        """Return a D1 cluster so evidence_json is guaranteed to be populated."""
        r1 = _make_record("r1", title="Evidence Test", doi="10.1234/evtest")
        r2 = _make_record("r2", title="Evidence Test alt", doi="10.1234/evtest")
        clusters = _cluster([r1, r2])
        self.assertEqual(len(clusters), 1)
        return clusters[0]

    def test_valid_json(self):
        """evidence_json must be a valid JSON string."""
        cluster = self._get_cluster_with_doi()
        try:
            parsed = json.loads(cluster.evidence_json)
        except json.JSONDecodeError as exc:
            self.fail(f"evidence_json is not valid JSON: {exc}")
        self.assertIsInstance(parsed, dict)

    def test_has_rule_field(self):
        """Parsed evidence_json must contain a 'rule' field."""
        cluster = self._get_cluster_with_doi()
        parsed = json.loads(cluster.evidence_json)
        self.assertIn("rule", parsed, "evidence_json missing 'rule' field")
        self.assertIn(parsed["rule"], ("D1", "D2", "D3"))


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
