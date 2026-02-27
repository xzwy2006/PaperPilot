"""
Prompt templates for AI-based structured data extraction in systematic reviews.
"""
from __future__ import annotations

SYSTEM_PROMPT = """You are a systematic review data extraction assistant. Your task is to extract structured information from academic paper text according to a predefined set of fields.

Guidelines:
- Extract information ONLY from the provided paper text.
- For each field, provide:
    - "value": the extracted value (must match the field type/options if given)
    - "confidence": a float between 0.0 and 1.0 indicating your certainty
    - "evidence": a short verbatim quote from the text supporting the value
- If information for a field cannot be found, set "value" to null and "confidence" to 0.0.
- For "select" type fields, "value" MUST be one of the provided options or null.
- For "bool" type fields, "value" MUST be true, false, or null.
- For "number" type fields, "value" MUST be a numeric value or null.
- Return ONLY valid JSON — no markdown fences, no extra commentary.
- Keep "evidence" concise (≤ 150 characters).
"""


def build_extraction_prompt(
    text: str,
    fields: list[dict],
    record_meta: dict,
) -> list[dict]:
    """
    Build an OpenAI-compatible messages list for structured data extraction.

    Parameters
    ----------
    text : str
        Full text content of the paper (or relevant excerpt).
    fields : list[dict]
        Field definitions, each containing:
            - "name" (str): machine-readable identifier
            - "description" (str): human-readable description / extraction hint
            - "type" (str): one of "text" | "number" | "bool" | "select"
            - "options" (list, optional): allowed values for "select" type
    record_meta : dict
        Bibliographic metadata:
            - "title" (str)
            - "authors" (str)
            - "year" (int)

    Returns
    -------
    list[dict]
        Messages list: [{"role": "system", ...}, {"role": "user", ...}]

    Expected AI response structure
    ------------------------------
    {
      "fields": {
        "<field_name>": {
          "value": <extracted value>,
          "confidence": 0.0-1.0,
          "evidence": "<verbatim quote from text>"
        }
      },
      "notes": "<any supplementary observations>"
    }
    """
    # ── Build field specification block ──────────────────────────────────────
    field_lines: list[str] = []
    for i, f in enumerate(fields, start=1):
        ftype = f.get("type", "text")
        fname = f.get("name", f"field_{i}")
        fdesc = f.get("description", "")
        fopts = f.get("options", [])

        line = f"  {i}. [{ftype.upper()}] {fname}: {fdesc}"
        if ftype == "select" and fopts:
            opts_str = ", ".join(f'"{o}"' for o in fopts)
            line += f" (allowed values: {opts_str})"
        field_lines.append(line)

    fields_block = "\n".join(field_lines)

    # ── Build JSON schema example ─────────────────────────────────────────────
    example_fields: dict = {}
    for f in fields:
        fname = f.get("name", "field")
        example_fields[fname] = {
            "value": None,
            "confidence": 0.0,
            "evidence": "",
        }
    json_schema = json_schema_str(example_fields)

    # ── Compose user message ──────────────────────────────────────────────────
    title   = record_meta.get("title", "Unknown")
    authors = record_meta.get("authors", "Unknown")
    year    = record_meta.get("year", "Unknown")

    user_content = f"""Paper metadata:
- Title:   {title}
- Authors: {authors}
- Year:    {year}

Fields to extract:
{fields_block}

Paper text:
"""
{text}
"""

Return your answer as JSON matching exactly this structure:
{json_schema}

Rules:
- Do NOT include markdown code fences.
- "confidence" must be a float in [0.0, 1.0].
- If a field cannot be determined, use null for "value" and 0.0 for "confidence".
- For select fields, "value" must be one of the listed options or null.
"""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_content},
    ]


# ── Internal helper ───────────────────────────────────────────────────────────

def json_schema_str(example_fields: dict) -> str:
    """Return a pretty-printed JSON skeleton for the expected response."""
    import json as _json
    skeleton = {
        "fields": example_fields,
        "notes": "<any supplementary observations>",
    }
    return _json.dumps(skeleton, indent=2, ensure_ascii=False)
