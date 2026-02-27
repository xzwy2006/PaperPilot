"""
paperpilot/core/ai/standardizer.py
Phase 9.1 — AI Text Standardization Engine
AIStandardizer: batch-normalise extracted field values via an LLM provider.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from paperpilot.core.ai.prompts.standardize import build_standardize_prompt

logger = logging.getLogger(__name__)


class AIStandardizer:
    """
    Normalises raw extracted field values to consistent, machine-readable form
    by calling an LLM through the given provider.

    Parameters
    ----------
    provider:
        Any object that exposes a `chat_completion(messages, model)` method
        returning a string (the LLM's text response).
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def standardize_field(
        self,
        field_name: str,
        field_type: str,
        raw_values: list[str],
        options: list[str] | None = None,
        unit: str | None = None,
        model: str | None = None,
    ) -> list[dict]:
        """
        批量标准化一组原始值。

        Parameters
        ----------
        field_name:  字段名称
        field_type:  "text" | "number" | "unit_value" | "select" | "bool"
        raw_values:  待标准化的原始字符串列表
        options:     select 类型的候选项列表
        unit:        unit_value 类型的目标单位字符串
        model:       可选的模型标识符，透传给 provider

        Returns
        -------
        list[dict] — 每项对应一个输入值:
            {
                "original":   str,
                "value":      Any,        # 标准化后的值
                "unit":       str | None,
                "confidence": float       # 0.0 – 1.0
            }

        Raises
        ------
        ValueError:    raw_values 为空或 field_type 不合法
        RuntimeError:  provider 调用失败或返回无法解析的 JSON
        """
        if not raw_values:
            raise ValueError("raw_values must not be empty")

        messages = build_standardize_prompt(
            field_name=field_name,
            field_type=field_type,
            raw_values=raw_values,
            options=options,
            unit=unit,
        )

        raw_response = self._call_provider(messages, model)
        results = self._parse_normalized_response(raw_response, raw_values)
        return results

    def standardize_record_fields(
        self,
        record_id: str,
        extracted_values: list[dict],    # 从 DB 读出的提取值列表
        field_definitions: list[dict],   # 字段定义（同 extraction）
        model: str | None = None,
        on_progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, list[dict]]:
        """
        对一条记录的所有字段逐一标准化。

        Parameters
        ----------
        record_id:         记录唯一标识
        extracted_values:  从数据库读取的提取值列表，每项格式：
                           {
                               "field_name": str,
                               "raw_value":  str,
                               ...
                           }
        field_definitions: 字段定义列表，每项至少包含:
                           {
                               "name":    str,
                               "type":    str,
                               "options": list[str] | None,  # select 类型
                               "unit":    str | None,        # unit_value 类型
                           }
        model:             可选的模型标识符
        on_progress:       进度回调 (field_name, current_index, total)

        Returns
        -------
        dict[str, list[dict]]
            {field_name: [normalized_result, ...]}

        Notes
        -----
        - 若某个字段标准化失败，记录错误并在结果中标记 confidence=0.0，
          不中断其余字段的处理。
        - field_definitions 中没有出现的字段将被跳过。
        """
        if not extracted_values:
            logger.warning("record %s: extracted_values is empty", record_id)
            return {}

        # 建立字段定义索引
        field_def_map: dict[str, dict] = {
            fd["name"]: fd for fd in field_definitions
        }

        # 按字段名分组收集原始值
        grouped: dict[str, list[str]] = {}
        for ev in extracted_values:
            fname = ev.get("field_name", "")
            rval = ev.get("raw_value", "")
            if fname and fname in field_def_map:
                grouped.setdefault(fname, []).append(rval)

        total = len(grouped)
        results: dict[str, list[dict]] = {}

        for idx, (field_name, raw_values) in enumerate(grouped.items()):
            if on_progress is not None:
                try:
                    on_progress(field_name, idx, total)
                except Exception:  # pragma: no cover
                    pass

            fd = field_def_map[field_name]
            try:
                normalized = self.standardize_field(
                    field_name=field_name,
                    field_type=fd.get("type", "text"),
                    raw_values=raw_values,
                    options=fd.get("options"),
                    unit=fd.get("unit"),
                    model=model,
                )
                results[field_name] = normalized
                logger.debug(
                    "record %s: field '%s' standardized (%d values)",
                    record_id, field_name, len(normalized),
                )
            except Exception as exc:
                logger.error(
                    "record %s: failed to standardize field '%s': %s",
                    record_id, field_name, exc,
                )
                # 降级：保留原始值，confidence=0
                results[field_name] = [
                    {
                        "original": rv,
                        "value": None,
                        "unit": None,
                        "confidence": 0.0,
                    }
                    for rv in raw_values
                ]

        if on_progress is not None:
            try:
                on_progress("__done__", total, total)
            except Exception:  # pragma: no cover
                pass

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _call_provider(
        self,
        messages: list[dict],
        model: str | None,
    ) -> str:
        """Call the underlying LLM provider and return its raw text output."""
        kwargs: dict[str, Any] = {"messages": messages}
        if model is not None:
            kwargs["model"] = model
        try:
            response = self._provider.chat_completion(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"Provider call failed: {exc}"
            ) from exc
        if isinstance(response, str):
            return response
        # Some providers return an object with a text attribute
        if hasattr(response, "text"):
            return response.text
        if hasattr(response, "content"):
            return response.content
        return str(response)

    def _parse_normalized_response(
        self,
        raw_response: str,
        raw_values: list[str],
    ) -> list[dict]:
        """Parse and validate the LLM's JSON response."""
        try:
            data = json.loads(raw_response.strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"LLM returned invalid JSON: {exc}\nRaw response:\n{raw_response}"
            ) from exc

        normalized = data.get("normalized")
        if not isinstance(normalized, list):
            raise RuntimeError(
                f"Expected 'normalized' list in response; got: {type(normalized)}"
            )

        # Ensure alignment with raw_values (pad / trim if model drifted)
        if len(normalized) != len(raw_values):
            logger.warning(
                "Response has %d entries but %d raw values were sent; "
                "aligning by index.",
                len(normalized), len(raw_values),
            )

        results: list[dict] = []
        for i, rv in enumerate(raw_values):
            if i < len(normalized):
                entry = normalized[i]
            else:
                entry = {}

            results.append(
                {
                    "original": entry.get("original", rv),
                    "value": entry.get("value"),
                    "unit": entry.get("unit"),
                    "confidence": float(entry.get("confidence", 0.0)),
                }
            )
        return results
