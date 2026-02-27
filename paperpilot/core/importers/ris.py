"""
paperpilot/core/importers/ris.py
RIS importer for PaperPilot — Phase 3.3
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


# RIS tag → standard field
_TAG_MAP: dict[str, str] = {
    "TI": "title",
    "T1": "title",
    "TT": "title",
    "CT": "title",
    "AB": "abstract",
    "N2": "abstract",
    "AU": "authors",
    "A1": "authors",
    "A2": "authors",
    "A3": "authors",
    "PY": "year",
    "Y1": "year",
    "DA": "year",
    "JO": "journal",
    "JF": "journal",
    "J1": "journal",
    "J2": "journal",
    "T2": "journal",
    "BT": "journal",
    "DO": "doi",
    "AN": "pmid",
    "KW": "keywords",
    "DE": "keywords",
    "ID": "keywords",
}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_RIS_LINE_RE = re.compile(r"^([A-Z][A-Z0-9])\s\s-\s?(.*)")


def _compute_title_norm(title: str) -> str:
    """Normalise title for dedup fingerprinting."""
    s = unicodedata.normalize("NFKC", title)
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    return s


class Record:
    """Lightweight container for a single RIS record."""

    __slots__ = (
        "title", "abstract", "authors", "year", "journal",
        "doi", "pmid", "keywords", "title_norm", "raw_import_blob",
    )

    def __init__(self, **kwargs):
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot, ""))

    def __repr__(self) -> str:  # pragma: no cover
        return f"Record(title={self.title!r}, doi={self.doi!r})"


def import_ris(path: str | Path, *, encoding: str = "utf-8-sig") -> list[Record]:
    """
    Parse *path* as a RIS file and return a list of :class:`Record` objects.

    Tries several encodings automatically (utf-8-sig → utf-8 → latin-1 → cp1252).
    The caller is responsible for writing records to the database.

    Parameters
    ----------
    path:
        Path to the RIS file.
    encoding:
        Primary encoding to try (default ``"utf-8-sig"``).

    Returns
    -------
    list[Record]
        One :class:`Record` per RIS entry (TY … ER block).
    """
    path = Path(path)
    records: list[Record] = []

    # Try multiple encodings
    content: str | None = None
    for enc in (encoding, "utf-8", "latin-1", "cp1252"):
        try:
            content = path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if content is None:
        return records

    current: dict[str, list[str]] = {}

    def _flush() -> None:
        if not current:
            return
        fields: dict[str, str] = {
            "title": "", "abstract": "", "authors": "", "year": "",
            "journal": "", "doi": "", "pmid": "", "keywords": "",
            "title_norm": "", "raw_import_blob": "",
        }
        author_parts: list[str] = []
        kw_parts: list[str] = []

        for tag, values in current.items():
            std = _TAG_MAP.get(tag)
            if std == "authors":
                author_parts.extend(v for v in values if v)
            elif std == "keywords":
                kw_parts.extend(v for v in values if v)
            elif std and values:
                val = values[-1].strip()
                if std == "year":
                    m = re.search(r"\b(\d{4})\b", val)
                    val = m.group(1) if m else val
                if not fields[std]:
                    fields[std] = val

        if author_parts:
            fields["authors"] = "; ".join(author_parts)
        if kw_parts:
            fields["keywords"] = "; ".join(kw_parts)

        fields["title_norm"] = _compute_title_norm(fields["title"])
        fields["raw_import_blob"] = json.dumps(
            {tag: vals for tag, vals in current.items()},
            ensure_ascii=False,
        )
        records.append(Record(**fields))
        current.clear()

    for line in content.splitlines():
        line = line.rstrip()
        m = _RIS_LINE_RE.match(line)
        if m:
            tag, value = m.group(1), m.group(2).strip()
            if tag == "ER":
                _flush()
            elif tag == "TY":
                if current:
                    _flush()
                current[tag] = [value]
            else:
                current.setdefault(tag, []).append(value)
        # blank lines or continuations between blocks — skip silently

    # Flush last record if file lacks a trailing ER tag
    if current:
        _flush()

    return records
