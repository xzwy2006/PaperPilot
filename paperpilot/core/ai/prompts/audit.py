"""
paperpilot/core/ai/prompts/audit.py
Phase 9.1 — AI Text Standardization Engine
Prompt builder for cross-field consistency audit (AI review).
"""

from __future__ import annotations

import json

AUDIT_SYSTEM_PROMPT = """You are a systematic review quality-control auditor.
Your job is to check whether extracted and standardized data values are internally consistent,
scientifically plausible, and free of obvious errors.
Always respond with valid JSON only, no markdown."""


def build_audit_prompt(
    record_meta: dict,
    extracted_fields: dict,    # {field_name: {value, confidence, evidence}}
    standardized_fields: dict, # {field_name: {value, unit, confidence}}
) -> list[dict]:
    """
    构建 messages，要求 AI 对提取+标准化结果做整体一致性检查。

    Parameters
    ----------
    record_meta:
        记录的元信息，例如：
        {
            "record_id": "rec_001",
            "title": "Effect of X on Y in ...",
            "study_type": "RCT",
            "population": "adult rats",
            ...
        }
    extracted_fields:
        从原文提取的字段字典，每项格式：
        {
            "field_name": {
                "value": <raw string>,
                "confidence": float,      # extractor 置信度
                "evidence": "<sentence>"  # 原文证据句
            }
        }
    standardized_fields:
        经 AI 标准化后的字段字典，每项格式：
        {
            "field_name": {
                "value": <normalized value>,
                "unit": str | None,
                "confidence": float       # standardizer 置信度
            }
        }

    Returns
    -------
    OpenAI-style messages list [{"role": ..., "content": ...}, ...]

    Expected LLM response schema
    ----------------------------
    {
      "overall_confidence": float,   // 0.0–1.0, aggregated quality score
      "flags": [
        {
          "field":    str,
          "issue":    str,
          "severity": "low" | "medium" | "high"
        }
      ],
      "notes": str   // free-text summary of the audit
    }
    """
    # ── serialise inputs ────────────────────────────────────────────────────
    meta_json = json.dumps(record_meta, ensure_ascii=False, indent=2)
    extracted_json = json.dumps(extracted_fields, ensure_ascii=False, indent=2)
    standardized_json = json.dumps(standardized_fields, ensure_ascii=False, indent=2)

    # ── user prompt ─────────────────────────────────────────────────────────
    user_content = (
        "You are reviewing the data extraction results for one study record.\n\n"
        "## Record metadata\n"
        f"```json\n{meta_json}\n```\n\n"
        "## Extracted field values (from source text)\n"
        f"```json\n{extracted_json}\n```\n\n"
        "## Standardized field values (normalized)\n"
        f"```json\n{standardized_json}\n```\n\n"
        "## Your task\n"
        "1. Check cross-field consistency (e.g., dose vs. dose_unit, age vs. age_group).\n"
        "2. Check scientific plausibility (e.g., doses, weights, durations within expected ranges).\n"
        "3. Check that standardized values faithfully represent the extracted evidence.\n"
        "4. Flag any suspicious, contradictory, or low-confidence values.\n\n"
        "Respond with a JSON object matching this schema exactly:\n"
        "{\n"
        '  "overall_confidence": <float 0.0–1.0>,\n'
        '  "flags": [\n'
        '    {\n'
        '      "field":    "<field name>",\n'
        '      "issue":    "<brief description of the problem>",\n'
        '      "severity": "low" | "medium" | "high"\n'
        '    }\n'
        "  ],\n"
        '  "notes": "<free-text summary>"\n'
        "}\n\n"
        "If no issues are found, return an empty flags array and overall_confidence close to 1.0. "
        "Respond with JSON only."
    )

    return [
        {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
