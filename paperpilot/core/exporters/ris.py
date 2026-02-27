"""
PaperPilot RIS Exporter
=======================
Exports screening records to RIS format with PaperPilot-specific extensions.

Encoding: UTF-8 with BOM (utf-8-sig) for Windows Excel / EndNote compatibility.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional


def export_ris(
    records: list[dict],
    decisions: dict[str, dict],          # record_id -> latest decision dict
    decision_history: dict[str, list[dict]],  # record_id -> [decision, ...]
    out_path: str,
    filter_decision: Optional[str] = None,   # None=all, "include"/"exclude"/"maybe"
) -> dict:
    """
    Export records to a RIS file with PaperPilot screening metadata.

    Parameters
    ----------
    records : list[dict]
        List of bibliographic record dicts.
    decisions : dict[str, dict]
        Mapping of record_id -> latest decision dict.
    decision_history : dict[str, list[dict]]
        Mapping of record_id -> list of historical decision dicts.
    out_path : str
        Output file path (.ris).
    filter_decision : str or None
        If set, only export records whose latest decision matches this value
        ("include", "exclude", "maybe").  None exports all records.

    Returns
    -------
    dict
        {"exported": int, "skipped": int}
    """
    exported = 0
    skipped = 0

    lines: list[str] = []

    for record in records:
        record_id = str(record.get("id", ""))
        latest = decisions.get(record_id) or {}

        # Apply filter
        if filter_decision is not None:
            decision_val = latest.get("decision", "")
            if decision_val != filter_decision:
                skipped += 1
                continue

        # ---- Standard fields -----------------------------------------------

        # TY - Type of reference (default JOUR if unknown)
        ref_type = record.get("type", "JOUR") or "JOUR"
        lines.append(f"TY  - {ref_type}")

        # ID tag (PaperPilot UUID)
        if record_id:
            lines.append(f"ID  - RPID:{record_id}")

        # TI - Title
        title = record.get("title", "")
        if title:
            lines.append(f"TI  - {title}")

        # AU - Authors (one per line)
        authors = record.get("authors") or record.get("author") or []
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(";") if a.strip()]
        for author in authors:
            lines.append(f"AU  - {author}")

        # JO - Journal / source
        journal = record.get("journal") or record.get("source") or record.get("container_title", "")
        if journal:
            lines.append(f"JO  - {journal}")

        # PY - Publication year
        year = record.get("year") or record.get("publication_year", "")
        if year:
            lines.append(f"PY  - {year}")

        # AB - Abstract
        abstract = record.get("abstract", "")
        if abstract:
            lines.append(f"AB  - {abstract}")

        # KW - Keywords (one per line)
        keywords = record.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(";") if k.strip()]
        for kw in keywords:
            lines.append(f"KW  - {kw}")

        # DO - DOI
        doi = record.get("doi", "")
        if doi:
            lines.append(f"DO  - {doi}")

        # UR - URL
        url = record.get("url") or record.get("uri", "")
        if url:
            lines.append(f"UR  - {url}")

        # ---- PaperPilot enhanced fields ------------------------------------

        # M1 - Fingerprint
        fingerprint = record.get("fingerprint", "")
        if fingerprint:
            lines.append(f"M1  - RPF:sha256:{fingerprint}")

        # N1 - Current screening decision
        if latest:
            decision_str = latest.get("decision", "")
            stage_str = latest.get("stage", "")
            reason_str = latest.get("reason", "")
            score_str = latest.get("score", "")
            # Normalise score to string
            if score_str is None:
                score_str = ""
            updated_str = latest.get("updated", "") or latest.get("ts", "") or str(date.today())
            # Trim to date portion if timestamp
            if "T" in str(updated_str):
                updated_str = str(updated_str).split("T")[0]
            n1_value = (
                f"PaperPilot Screening Current"
                f"|decision={decision_str}"
                f"|stage={stage_str}"
                f"|reason={reason_str}"
                f"|score={score_str}"
                f"|protocol=default"
                f"|updated={updated_str}"
            )
            lines.append(f"N1  - {n1_value}")

        # N2 - Historical decisions (one line each)
        history = decision_history.get(record_id) or []
        for entry in history:
            log_obj = {
                "id": str(entry.get("id", "")),
                "decision": str(entry.get("decision", "")),
                "reason_code": str(entry.get("reason_code", "") or entry.get("reason", "")),
                "ts": str(entry.get("ts", "") or entry.get("updated", "")),
            }
            lines.append(f"N2  - PaperPilot Screening Log {json.dumps(log_obj, ensure_ascii=False)}")

        # End of record
        lines.append("ER  - ")
        lines.append("")   # blank line between records

        exported += 1

    # Write file with UTF-8 BOM
    content = "\r\n".join(lines)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(content)

    return {"exported": exported, "skipped": skipped}
