"""
tests/test_csv_importer.py
Unit tests for the PaperPilot CSV importer — Phase 3.1
"""
from __future__ import annotations

import csv
import json
import tempfile
import unicodedata
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import the module under test.
# Adjust the import path to match the installed package structure.
# ---------------------------------------------------------------------------
import importlib, sys

def _load_csv_importer():
    """Dynamically import the csv importer regardless of working directory."""
    # Try the package path first (when run from repo root)
    try:
        from paperpilot.core.importers.csv import import_csv, compute_title_norm, Record
        return import_csv, compute_title_norm, Record
    except ImportError:
        pass
    # Fallback: load from a local copy (useful in CI without installed package)
    import importlib.util, os
    candidates = [
        Path(__file__).parent.parent / "paperpilot" / "core" / "importers" / "csv.py",
        Path(__file__).parent.parent / "csv_importer.py",
    ]
    for p in candidates:
        if p.exists():
            spec = importlib.util.spec_from_file_location("_csv_importer", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.import_csv, mod.compute_title_norm, mod.Record
    raise ImportError("Cannot find csv importer module")


import_csv, compute_title_norm, Record = _load_csv_importer()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
FIXTURE_ROWS = [
    {
        "Title": "Systematic Review of Machine Learning in Medicine",
        "Abstract": "A comprehensive review covering ML applications in clinical settings.",
        "Authors": "Smith J; Doe A; Lee K",
        "Year": "2023",
        "Journal": "Journal of Medical AI",
        "DOI": "10.1000/xyz123",
        "PMID": "12345678",
        "Keywords": "machine learning; medicine; systematic review",
    },
    {
        # Mixed-case column names on purpose to test case-insensitive mapping
        "TITLE": "Deep Learning for Drug Discovery",
        "ABSTRACT": "An overview of deep learning approaches for pharmaceutical research.",
        "author": "Brown P",
        "pub_year": "2021",
        "source": "Nature Reviews Drug Discovery",
        "doi": "10.1038/abcde",
        "PubMed_ID": "",   # unknown column — should be ignored
        "KEY WORDS": "deep learning; drug discovery",
    },
    {
        # Row with Unicode title to test NFKC normalisation
        "Title": "Hépatite\u2019s Impact on Héalth: A Révièw",
        "Abstract": "",
        "Authors": "",
        "Year": "",
        "Journal": "",
        "DOI": "",
        "PMID": "",
        "Keywords": "",
    },
]


def _write_fixture_csv(path: Path, rows: list[dict]) -> None:
    """Write *rows* to *path* as CSV, using the union of all keys as headers."""
    all_keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=all_keys, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture()
def fixture_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "test_papers.csv"
    _write_fixture_csv(csv_path, FIXTURE_ROWS)
    return csv_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComputeTitleNorm:
    def test_basic_lower(self):
        assert compute_title_norm("Hello World") == "hello world"

    def test_strips_punctuation(self):
        result = compute_title_norm("Hello, World!")
        assert "," not in result
        assert "!" not in result

    def test_nkfc_normalisation(self):
        # Ligature fi → fi (two chars)
        result = compute_title_norm("\ufb01le")  # ﬁle
        assert "fi" in result

    def test_collapses_whitespace(self):
        assert compute_title_norm("  foo   bar  ") == "foo bar"

    def test_unicode_accents_kept(self):
        # Accented characters are lower-cased but not stripped
        result = compute_title_norm("Hépatite")
        assert "hépatite" == result

    def test_apostrophe_removed(self):
        result = compute_title_norm("Hépatite\u2019s Impact")
        assert "\u2019" not in result


class TestImportCSV:
    def test_returns_list_of_records(self, fixture_csv):
        records = import_csv(fixture_csv)
        assert isinstance(records, list)
        assert len(records) == 3

    def test_first_record_field_mapping(self, fixture_csv):
        records = import_csv(fixture_csv)
        r = records[0]
        assert r.title == "Systematic Review of Machine Learning in Medicine"
        assert r.abstract.startswith("A comprehensive review")
        assert r.authors == "Smith J; Doe A; Lee K"
        assert r.year == "2023"
        assert r.journal == "Journal of Medical AI"
        assert r.doi == "10.1000/xyz123"
        assert r.pmid == "12345678"
        assert "machine learning" in r.keywords

    def test_case_insensitive_column_mapping(self, fixture_csv):
        """Second row uses TITLE, author, pub_year, source, doi — all caps/snake."""
        records = import_csv(fixture_csv)
        r = records[1]
        assert r.title == "Deep Learning for Drug Discovery"
        assert r.authors == "Brown P"
        assert r.year == "2021"
        assert r.journal == "Nature Reviews Drug Discovery"
        assert r.doi == "10.1038/abcde"

    def test_title_norm_computed(self, fixture_csv):
        records = import_csv(fixture_csv)
        r = records[0]
        # title_norm should be lower-case, no punctuation
        assert r.title_norm == compute_title_norm(r.title)
        assert r.title_norm == r.title_norm.lower()

    def test_title_norm_unicode(self, fixture_csv):
        """Third row has Unicode title — NFKC + lower + strip punct."""
        records = import_csv(fixture_csv)
        r = records[2]
        assert r.title_norm  # non-empty
        assert r.title_norm == r.title_norm.lower()
        # curly apostrophe should be gone
        assert "\u2019" not in r.title_norm

    def test_raw_import_blob_exists(self, fixture_csv):
        records = import_csv(fixture_csv)
        for r in records:
            assert r.raw_import_blob, "raw_import_blob must not be empty"

    def test_raw_import_blob_is_valid_json(self, fixture_csv):
        records = import_csv(fixture_csv)
        for r in records:
            blob = json.loads(r.raw_import_blob)
            assert isinstance(blob, dict)

    def test_raw_import_blob_contains_original_keys(self, fixture_csv):
        """Blob must preserve original (unmapped) CSV column names."""
        records = import_csv(fixture_csv)
        blob0 = json.loads(records[0].raw_import_blob)
        # Original CSV has 'Title' (capital T)
        assert "Title" in blob0

    def test_empty_csv_returns_empty_list(self, tmp_path):
        empty = tmp_path / "empty.csv"
        empty.write_text("Title,Abstract,Authors\n", encoding="utf-8")
        assert import_csv(empty) == []

    def test_record_has_all_standard_fields(self, fixture_csv):
        records = import_csv(fixture_csv)
        r = records[0]
        for field in ("title", "abstract", "authors", "year", "journal",
                      "doi", "pmid", "keywords", "title_norm", "raw_import_blob"):
            assert hasattr(r, field), f"Record missing field: {field}"
