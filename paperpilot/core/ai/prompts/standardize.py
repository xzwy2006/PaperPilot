"""
paperpilot/core/ai/prompts/standardize.py
Phase 9.1 — AI Text Standardization Engine
Prompt builders for field-value normalization.
"""

from __future__ import annotations

import json

SYSTEM_PROMPT = """You are a systematic review data standardization assistant.
Your job is to normalize extracted values to a consistent, machine-readable format.
Always respond with valid JSON only, no markdown."""


def build_standardize_prompt(
    field_name: str,
    field_type: str,           # "text" | "number" | "unit_value" | "select" | "bool"
    raw_values: list[str],     # 多条记录的原始提取值
    options: list[str] | None = None,  # select 类型的候选项
    unit: str | None = None,           # unit_value 的目标单位（如 "mg/kg/day"）
) -> list[dict]:
    """
    构建 messages，要求 AI 返回：
    {
      "normalized": [
        {"original": "...", "value": <标准值>, "unit": "...", "confidence": 0.0-1.0}
      ]
    }

    Args:
        field_name:  字段名称，如 "dose", "age", "sex"
        field_type:  字段类型，决定标准化规则
        raw_values:  待标准化的原始字符串列表
        options:     当 field_type == "select" 时提供可选项
        unit:        当 field_type == "unit_value" 时提供目标单位

    Returns:
        OpenAI-style messages list [{"role": ..., "content": ...}, ...]
    """
    if not raw_values:
        raise ValueError("raw_values must not be empty")

    # ── type-specific instructions ──────────────────────────────────────────
    type_instructions: dict[str, str] = {
        "text": (
            "Normalize the text: fix spelling, standardize capitalization, "
            "expand abbreviations if unambiguous. "
            'Return the normalized string as "value". '
            '"unit" should always be null for text fields.'
        ),
        "number": (
            "Convert the raw string to a numeric value (int or float). "
            "Handle written numbers (e.g., 'three' → 3), ranges (use midpoint), "
            "and approximate markers (e.g., '~10' → 10). "
            'Return the numeric value as "value", "unit" as null.'
        ),
        "unit_value": (
            f"Convert the raw string to a numeric value expressed in the target unit: "
            f'"{unit or "SI base unit"}". '
            "Apply unit conversion if necessary (e.g., mg → g, lb → kg). "
            'Return the converted numeric value as "value" and the target unit string as "unit".'
        ),
        "select": (
            f"Map the raw string to exactly one of the allowed options: "
            f"{json.dumps(options or [])}. "
            "Choose the closest match. If no match is possible, set value to null. "
            '"unit" should always be null for select fields.'
        ),
        "bool": (
            "Interpret the raw string as a boolean. "
            "Positive indicators (yes, true, 1, reported, present, …) → true. "
            "Negative indicators (no, false, 0, not reported, absent, …) → false. "
            "If ambiguous, set value to null. "
            '"unit" should always be null for boolean fields.'
        ),
    }

    if field_type not in type_instructions:
        raise ValueError(
            f"Unknown field_type '{field_type}'. "
            f"Must be one of: {list(type_instructions.keys())}"
        )

    # ── build user message ───────────────────────────────────────────────────
    values_json = json.dumps(raw_values, ensure_ascii=False)
    instruction = type_instructions[field_type]

    user_content = (
        f'Standardize the following extracted values for field "{field_name}" '
        f'(type: {field_type}).\n\n'
        f"Instructions: {instruction}\n\n"
        f"Raw values (JSON array):\n{values_json}\n\n"
        "Return a JSON object with this exact schema:\n"
        '{\n'
        '  "normalized": [\n'
        '    {\n'
        '      "original": "<the raw input string>",\n'
        '      "value": <normalized value or null>,\n'
        '      "unit": "<unit string or null>",\n'
        '      "confidence": <float 0.0–1.0>\n'
        '    }\n'
        '  ]\n'
        '}\n\n'
        "One entry per raw value, in the same order. "
        "confidence reflects how certain you are about the normalization. "
        "Respond with JSON only."
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
