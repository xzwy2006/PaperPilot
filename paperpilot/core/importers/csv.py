"""
paperpilot/core/importers/csv.py
CSV importer for PaperPilot — Phase 3.1
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Column-name → standard field mapping (case-insensitive)
# ---------------------------------------------------------------------------
_COLUMN_ALIASES: dict[str, list[str]] = {
    "title": [
        "title", "article title", "article_title", "paper title", "paper_title",
        "document title", "document_title", "name",
    ],
    "abstract": [
        "abstract", "abstracts", "abstract text", "abstract_text",
        "description", "summary",
    ],
    "authors": [
        "authors", "author", "author names", "author_names",
        "author list", "author_list", "creator", "creators",
    ],
    "year": [
        "year", "pub year", "pub_year", "publication year",
        "publication_year", "pubdate", "pub date", "pub_date",
        "year published", "year_published",
    ],
    "journal": [
        "journal", "journal name", "journal_name", "source", "publication",
        "journal title", "journal_title", "periodical",
    ],
    "doi": [
        "doi", "digital object identifier", "doi number",
    ],
    "pmid": [
        "pmid", "pubmed id", "pubmed_id", "pubmedid",
        "medline pmid", "medline_pmid",
    ],
    "keywords": [
        "keywords", "keyword", "key words", "key_words",
        "mesh terms", "mesh_terms", "author keywords", "author_keywords",
        "index terms", "index_terms",
    ],
}

# Build reverse lookup: lowercased alias → standard field name
_ALIAS_MAP: dict[str, str] = {}
for _field, _aliases in _COLUMN_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_MAP[_alias.lower()] = _field


def _resolve_column(col_name: str) -> str | None:
    """Return the standard field name for *col_name*, or None if unknown."""
    return _ALIAS_MAP.get(col_name.strip().lower())


# ---------------------------------------------------------------------------
# title_norm computation
# ---------------------------------------------------------------------------
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def compute_title_norm(title: str) -> str:
    """Unicode NFKC → lower → strip punctuation → collapse whitespace."""
    s = unicodedata.normalize("NFKC", title)
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    return s


# ---------------------------------------------------------------------------
# Simple Record dataclass (pure-Python, no DB dependency)
# ---------------------------------------------------------------------------
class Record:
    """Lightweight container for a single paper record."""

    __slots__ = (
        "title",
        "abstract",
        "authors",
        "year",
        "journal",
        "doi",
        "pmid",
        "keywords",
        "title_norm",
        "raw_import_blob",
    )

    def __init__(
        self,
        *,
        title: str = "",
        abstract: str = "",
        authors: str = "",
        year: str = "",
        journal: str = "",
        doi: str = "",
        pmid: str = "",
        keywords: str = "",
        title_norm: str = "",
        raw_import_blob: str = "",
    ) -> None:
        self.title = title
        self.abstract = abstract
        self.authors = authors
        self.year = year
        self.journal = journal
        self.doi = doi
        self.pmid = pmid
        self.keywords = keywords
        self.title_norm = title_norm
        self.raw_import_blob = raw_import_blob

    def __repr__(self) -> str:  # pragma: no cover
        return f"Record(title={self.title!r}, doi={self.doi!r})"


# ---------------------------------------------------------------------------
# Public importer function
# ---------------------------------------------------------------------------

def import_csv(
    path: str | Path,
    *,
    encoding: str = "utf-8-sig",
    delimiter: str = ",",
) -> list[Record]:
    """
    Parse *path* as a CSV file and return a list of :class:`Record` objects.

    The caller is responsible for writing these records to the database.

    Parameters
    ----------
    path:
        Path to the CSV file.
    encoding:
        File encoding (default ``"utf-8-sig"`` handles BOM-prefixed UTF-8).
    delimiter:
        Column delimiter (default ``","``).

    Returns
    -------
    list[Record]
        One :class:`Record` per non-empty CSV row.
    """
    path = Path(path)
    records: list[Record] = []

    with path.open(newline="", encoding=encoding) as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        if reader.fieldnames is None:
            return records  # empty file

        # Map each CSV column header to a standard field (or None = unmapped)
        col_mapping: dict[str, str | None] = {
            col: _resolve_column(col) for col in reader.fieldnames
        }

        for raw_row in reader:
            # Skip completely empty rows
            if not any(v.strip() for v in raw_row.values() if v):
                continue

            fields: dict[str, Any] = {
                "title": "",
                "abstract": "",
                "authors": "",
                "year": "",
                "journal": "",
                "doi": "",
                "pmid": "",
                "keywords": "",
            }

            for col, value in raw_row.items():
                std = col_mapping.get(col)
                if std and value:
                    # For multi-value fields prefer first non-empty mapping
                    if not fields[std]:
                        fields[std] = value.strip()

            # Derived fields
            fields["title_norm"] = compute_title_norm(fields["title"])
            fields["raw_import_blob"] = json.dumps(
                {k: (v if v is not None else "") for k, v in raw_row.items()},
                ensure_ascii=False,
            )

            records.append(Record(**fields))

    return records
