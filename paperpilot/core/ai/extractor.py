"""
AI-based structured data extractor for PaperPilot systematic reviews.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from paperpilot.core.ai.prompts.extraction import build_extraction_prompt

logger = logging.getLogger(__name__)


class AIExtractor:
    """
    Extracts structured data fields from paper text using an AI provider.

    Parameters
    ----------
    provider : object
        Any AI provider that exposes a ``chat(messages, model=None)`` method
        returning a dict with at least::

            {
                "content": str,          # the model's reply text
                "model": str,            # model identifier used
                "usage": {               # token usage (optional keys)
                    "prompt_tokens": int,
                    "completion_tokens": int,
                    "total_tokens": int,
                },
            }
    """

    def __init__(self, provider) -> None:
        self._provider = provider

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def extract(
        self,
        record: dict,
        pdf_text: str,
        fields: list[dict],
        model: str | None = None,
    ) -> dict:
        """
        Extract structured field values from a single paper.

        Parameters
        ----------
        record : dict
            Record metadata, e.g. ``{"title": ..., "authors": ..., "year": ...}``.
        pdf_text : str
            Full text of the paper (obtained from PDF parsing).
        fields : list[dict]
            Field definitions (same format as ``build_extraction_prompt``).
        model : str | None
            Override the provider's default model.

        Returns
        -------
        dict
            On success::

                {
                    "fields": {
                        "<field_name>": {
                            "value": ...,
                            "confidence": float,   # clamped to [0.0, 1.0]
                            "evidence": str,
                        }
                    },
                    "notes": str,
                    "raw_response": str,
                    "model": str,
                    "usage": dict,
                }

            On JSON parse failure::

                {
                    "error": str,
                    "raw_response": str,
                }
        """
        # 1. Build prompt messages
        record_meta = {
            "title":   record.get("title", ""),
            "authors": record.get("authors", ""),
            "year":    record.get("year", ""),
        }
        messages = build_extraction_prompt(pdf_text, fields, record_meta)

        # 2. Call provider
        try:
            kwargs: dict = {}
            if model is not None:
                kwargs["model"] = model
            response = self._provider.chat(messages, **kwargs)
        except Exception as exc:
            logger.error("Provider call failed: %s", exc)
            return {"error": str(exc), "raw_response": ""}

        raw_response: str = response.get("content", "")
        used_model: str   = response.get("model", model or "")
        usage: dict       = response.get("usage", {})

        # 3. Parse JSON
        try:
            data = self._parse_json(raw_response)
        except ValueError as exc:
            logger.warning("JSON parse failed for record %r: %s", record.get("id"), exc)
            return {"error": str(exc), "raw_response": raw_response}

        # 4. Validate & clamp confidence values
        extracted_fields: dict = {}
        for field_name, field_data in data.get("fields", {}).items():
            if not isinstance(field_data, dict):
                field_data = {"value": field_data, "confidence": 0.0, "evidence": ""}

            raw_conf = field_data.get("confidence", 0.0)
            try:
                confidence = float(raw_conf)
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))   # clamp to [0, 1]

            extracted_fields[field_name] = {
                "value":      field_data.get("value"),
                "confidence": confidence,
                "evidence":   str(field_data.get("evidence", "")),
            }

        return {
            "fields":       extracted_fields,
            "notes":        str(data.get("notes", "")),
            "raw_response": raw_response,
            "model":        used_model,
            "usage":        usage,
        }

    def batch_extract(
        self,
        records: list[dict],
        pdf_texts: dict[str, str],
        fields: list[dict],
        model: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, dict]:
        """
        Extract data for a list of records.

        Parameters
        ----------
        records : list[dict]
            Each record must have an ``"id"`` key used to look up ``pdf_texts``.
        pdf_texts : dict[str, str]
            Mapping of ``record["id"]`` → full paper text.
        fields : list[dict]
            Field definitions shared across all records.
        model : str | None
            Override model for all extractions.
        on_progress : callable | None
            Called as ``on_progress(current, total)`` after each record.

        Returns
        -------
        dict[str, dict]
            Mapping of ``record["id"]`` → extraction result dict.
        """
        total = len(records)
        results: dict[str, dict] = {}

        for idx, record in enumerate(records, start=1):
            record_id = record.get("id", str(idx))
            pdf_text  = pdf_texts.get(record_id, "")

            if not pdf_text:
                logger.warning("No PDF text for record %r — skipping.", record_id)
                results[record_id] = {
                    "error": "No PDF text available",
                    "raw_response": "",
                }
            else:
                results[record_id] = self.extract(
                    record=record,
                    pdf_text=pdf_text,
                    fields=fields,
                    model=model,
                )

            if on_progress is not None:
                try:
                    on_progress(idx, total)
                except Exception:  # noqa: BLE001
                    pass

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(text: str) -> dict:
        """
        Parse JSON from the model's raw reply.

        Strips optional markdown fences (```json ... ```) before parsing.

        Raises
        ------
        ValueError
            If the text cannot be decoded as valid JSON.
        """
        stripped = text.strip()

        # Remove markdown code fences if present
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            # Drop first line (``` or ```json) and last line (```)
            inner_lines = lines[1:]
            if inner_lines and inner_lines[-1].strip() == "```":
                inner_lines = inner_lines[:-1]
            stripped = "\n".join(inner_lines).strip()

        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON from AI response: {exc}") from exc
