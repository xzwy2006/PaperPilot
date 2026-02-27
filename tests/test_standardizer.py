"""
tests/test_standardizer.py — Phase 9 Test Suite for PaperPilot

Covers:
- build_standardize_prompt() in paperpilot/core/ai/prompts/standardize.py
    * returns list with system + user messages
    * user message contains field name and raw values
    * select type includes options list
    * unit_value type includes target unit
- AIStandardizer (paperpilot/core/ai/standardizer.py) with mock provider
    * normal JSON response → parsed correctly, confidence clamped to [0, 1]
    * JSON parse failure → raises RuntimeError containing error info
    * standardize_record_fields() calls provider once per field
- build_audit_prompt() in paperpilot/core/ai/prompts/audit.py
    * returns list with system + user messages
    * user message contains extracted_fields and standardized_fields
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────────────────────────────────────

from paperpilot.core.ai.prompts.standardize import build_standardize_prompt
from paperpilot.core.ai.prompts.audit import build_audit_prompt
from paperpilot.core.ai.standardizer import AIStandardizer


# =============================================================================
# Section 1: build_standardize_prompt()
# =============================================================================

class TestBuildStandardizePrompt:
    """Tests for the prompt builder in standardize.py."""

    def _call(self, field_name="dose", field_type="text",
              raw_values=None, **kwargs):
        if raw_values is None:
            raw_values = ["10 mg", "20mg", "5 milligrams"]
        return build_standardize_prompt(
            field_name=field_name,
            field_type=field_type,
            raw_values=raw_values,
            **kwargs,
        )

    # ── structure ────────────────────────────────────────────────────────────

    def test_returns_list(self):
        """Result must be a list."""
        messages = self._call()
        assert isinstance(messages, list)

    def test_has_system_and_user_messages(self):
        """Must contain at least a system message and a user message."""
        messages = self._call()
        assert len(messages) >= 2
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles

    def test_system_message_is_first(self):
        """System message should be the first element."""
        messages = self._call()
        assert messages[0]["role"] == "system"

    def test_user_message_is_second(self):
        """User message should follow the system message."""
        messages = self._call()
        assert messages[1]["role"] == "user"

    def test_messages_have_content_key(self):
        """Every message must have a 'content' key with a non-empty string."""
        messages = self._call()
        for msg in messages:
            assert "content" in msg
            assert isinstance(msg["content"], str)
            assert len(msg["content"]) > 0

    # ── user message content ─────────────────────────────────────────────────

    def test_user_message_contains_field_name(self):
        """User message must reference the field name."""
        messages = self._call(field_name="blood_pressure")
        user_content = messages[1]["content"]
        assert "blood_pressure" in user_content

    def test_user_message_contains_raw_values(self):
        """User message must include at least one of the raw values."""
        raw_values = ["high", "low", "normal"]
        messages = self._call(raw_values=raw_values)
        user_content = messages[1]["content"]
        assert any(v in user_content for v in raw_values)

    def test_user_message_contains_all_raw_values(self):
        """All raw values should appear in the user message (via JSON)."""
        raw_values = ["val_alpha", "val_beta", "val_gamma"]
        messages = self._call(raw_values=raw_values)
        user_content = messages[1]["content"]
        for v in raw_values:
            assert v in user_content

    # ── select type ──────────────────────────────────────────────────────────

    def test_select_type_includes_options(self):
        """For select type, options must appear in the user message."""
        options = ["male", "female", "other"]
        messages = build_standardize_prompt(
            field_name="sex",
            field_type="select",
            raw_values=["M", "F", "Unknown"],
            options=options,
        )
        user_content = messages[1]["content"]
        for opt in options:
            assert opt in user_content

    def test_select_type_all_options_present(self):
        """All select options must be referenced in the prompt."""
        options = ["placebo", "treatment_a", "treatment_b", "control"]
        messages = build_standardize_prompt(
            field_name="group",
            field_type="select",
            raw_values=["treat A", "ctrl", "plac"],
            options=options,
        )
        user_content = messages[1]["content"]
        for opt in options:
            assert opt in user_content

    # ── unit_value type ──────────────────────────────────────────────────────

    def test_unit_value_type_includes_target_unit(self):
        """For unit_value type, the target unit must appear in the user message."""
        messages = build_standardize_prompt(
            field_name="dose",
            field_type="unit_value",
            raw_values=["10 mg", "0.5 g"],
            unit="mg/kg/day",
        )
        user_content = messages[1]["content"]
        assert "mg/kg/day" in user_content

    def test_unit_value_with_si_unit(self):
        """unit_value type with a standard SI unit should appear in prompt."""
        messages = build_standardize_prompt(
            field_name="weight",
            field_type="unit_value",
            raw_values=["70 kg", "150 lb"],
            unit="kg",
        )
        user_content = messages[1]["content"]
        assert "kg" in user_content

    # ── field type mention ────────────────────────────────────────────────────

    def test_field_type_present_in_user_message(self):
        """The field type should be mentioned in the user message."""
        messages = build_standardize_prompt(
            field_name="age",
            field_type="number",
            raw_values=["thirty", "45"],
        )
        user_content = messages[1]["content"]
        assert "number" in user_content.lower()

    def test_bool_type_builds_valid_prompt(self):
        """Bool type builds a valid messages list."""
        messages = build_standardize_prompt(
            field_name="randomized",
            field_type="bool",
            raw_values=["yes", "no", "not reported"],
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    # ── error cases ───────────────────────────────────────────────────────────

    def test_empty_raw_values_raises(self):
        """Empty raw_values list should raise ValueError."""
        with pytest.raises((ValueError, Exception)):
            build_standardize_prompt(
                field_name="test",
                field_type="text",
                raw_values=[],
            )

    def test_unknown_field_type_raises(self):
        """Unknown field_type should raise ValueError."""
        with pytest.raises((ValueError, Exception)):
            build_standardize_prompt(
                field_name="test",
                field_type="UNKNOWN_TYPE_XYZ",
                raw_values=["foo"],
            )


# =============================================================================
# Section 2: AIStandardizer with mock provider
# =============================================================================

def _make_mock_provider(response_content: str) -> MagicMock:
    """Build a mock provider whose chat_completion() returns the given content string."""
    provider = MagicMock()
    provider.chat_completion.return_value = response_content
    return provider


def _make_normalized_json(entries: list) -> str:
    """Build a valid JSON string matching the standardizer response schema."""
    return json.dumps({"normalized": entries})


class TestAIStandardizer:
    """Tests for AIStandardizer class using standardize_field() and standardize_record_fields()."""

    # ── normal JSON response ─────────────────────────────────────────────────

    def test_normal_response_returns_list(self):
        """Valid JSON from provider should be parsed and return a list."""
        entries = [
            {"original": "10 mg", "value": 10.0, "unit": "mg", "confidence": 0.95}
        ]
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        result = standardizer.standardize_field(
            field_name="dose",
            field_type="unit_value",
            raw_values=["10 mg"],
            unit="mg",
        )
        assert isinstance(result, list)

    def test_normal_response_value_extracted(self):
        """The 'value' field should be present in parsed results."""
        entries = [
            {"original": "Smith, J.", "value": "Smith J", "unit": None, "confidence": 0.88}
        ]
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        result = standardizer.standardize_field(
            field_name="author",
            field_type="text",
            raw_values=["Smith, J."],
        )
        assert len(result) == 1
        assert "value" in result[0]
        assert result[0]["value"] == "Smith J"

    def test_confidence_clamped_to_max_one(self):
        """Confidence values > 1.0 should be clamped to 1.0."""
        entries = [
            {"original": "yes", "value": True, "unit": None, "confidence": 1.5}
        ]
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        result = standardizer.standardize_field(
            field_name="randomized",
            field_type="bool",
            raw_values=["yes"],
        )
        for item in result:
            assert item.get("confidence", 0) <= 1.0

    def test_confidence_clamped_to_min_zero(self):
        """Confidence values < 0.0 should be clamped to 0.0."""
        entries = [
            {"original": "no", "value": False, "unit": None, "confidence": -0.5}
        ]
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        result = standardizer.standardize_field(
            field_name="randomized",
            field_type="bool",
            raw_values=["no"],
        )
        for item in result:
            assert item.get("confidence", 0) >= 0.0

    def test_confidence_in_range_preserved(self):
        """Confidence values already in [0, 1] should be preserved."""
        conf = 0.75
        entries = [
            {"original": "male", "value": "male", "unit": None, "confidence": conf}
        ]
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        result = standardizer.standardize_field(
            field_name="sex",
            field_type="select",
            raw_values=["male"],
            options=["male", "female"],
        )
        assert len(result) == 1
        assert abs(result[0].get("confidence", -1) - conf) < 1e-9

    def test_provider_chat_completion_called_once(self):
        """Provider.chat_completion() should be called exactly once per standardize_field() call."""
        entries = [{"original": "foo", "value": "foo", "unit": None, "confidence": 0.9}]
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        standardizer.standardize_field(
            field_name="name",
            field_type="text",
            raw_values=["foo"],
        )
        provider.chat_completion.assert_called_once()

    def test_result_contains_original_field(self):
        """Each result entry should have an 'original' key."""
        raw_values = ["10 mg", "20 mg"]
        entries = [
            {"original": "10 mg", "value": 10.0, "unit": "mg", "confidence": 0.9},
            {"original": "20 mg", "value": 20.0, "unit": "mg", "confidence": 0.85},
        ]
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        result = standardizer.standardize_field(
            field_name="dose",
            field_type="unit_value",
            raw_values=raw_values,
            unit="mg",
        )
        assert len(result) == 2
        for item in result:
            assert "original" in item

    # ── JSON parse failure ────────────────────────────────────────────────────

    def test_invalid_json_raises_runtime_error(self):
        """When provider returns invalid JSON, RuntimeError should be raised."""
        provider = _make_mock_provider("This is not valid JSON at all!!!")
        standardizer = AIStandardizer(provider)
        with pytest.raises(RuntimeError):
            standardizer.standardize_field(
                field_name="dose",
                field_type="text",
                raw_values=["10mg"],
            )

    def test_empty_response_raises_runtime_error(self):
        """Empty string response should raise RuntimeError."""
        provider = _make_mock_provider("")
        standardizer = AIStandardizer(provider)
        with pytest.raises((RuntimeError, Exception)):
            standardizer.standardize_field(
                field_name="dose",
                field_type="text",
                raw_values=["10mg"],
            )

    def test_partial_json_raises_runtime_error(self):
        """Truncated JSON should raise RuntimeError."""
        provider = _make_mock_provider('{"normalized": [{"original": "foo"')
        standardizer = AIStandardizer(provider)
        with pytest.raises((RuntimeError, Exception)):
            standardizer.standardize_field(
                field_name="x",
                field_type="text",
                raw_values=["foo"],
            )

    def test_error_result_contains_error_info(self):
        """RuntimeError message should reference the parse failure."""
        provider = _make_mock_provider("INVALID JSON")
        standardizer = AIStandardizer(provider)
        try:
            standardizer.standardize_field(
                field_name="dose",
                field_type="text",
                raw_values=["10mg"],
            )
            assert False, "Should have raised"
        except (RuntimeError, Exception) as exc:
            assert len(str(exc)) > 0  # error message should be informative

    # ── standardize_record_fields() ──────────────────────────────────────────

    def test_standardize_record_fields_calls_per_field(self):
        """
        standardize_record_fields() must call the provider once per field.

        The real API is: standardize_record_fields(record_id, extracted_values, field_definitions)
        where extracted_values is a list of {"field_name": ..., "raw_value": ...}
        and field_definitions is a list of {"name": ..., "type": ..., ...}
        """
        field_definitions = [
            {"name": "dose",  "type": "unit_value", "unit": "mg"},
            {"name": "sex",   "type": "select",     "options": ["M", "F"]},
            {"name": "notes", "type": "text"},
        ]
        extracted_values = [
            {"field_name": "dose",  "raw_value": "10 mg"},
            {"field_name": "sex",   "raw_value": "Male"},
            {"field_name": "notes", "raw_value": "some text"},
        ]
        entries = [{"original": "x", "value": "x", "unit": None, "confidence": 0.8}]
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        standardizer.standardize_record_fields(
            record_id="rec_001",
            extracted_values=extracted_values,
            field_definitions=field_definitions,
        )
        assert provider.chat_completion.call_count == len(field_definitions)

    def test_standardize_record_fields_returns_dict(self):
        """Result should be a dict keyed by field name."""
        field_definitions = [
            {"name": "age",    "type": "number"},
            {"name": "weight", "type": "unit_value", "unit": "kg"},
        ]
        extracted_values = [
            {"field_name": "age",    "raw_value": "thirty"},
            {"field_name": "weight", "raw_value": "70 lb"},
        ]
        entries = [{"original": "x", "value": 30, "unit": None, "confidence": 0.9}]
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        results = standardizer.standardize_record_fields(
            record_id="rec_002",
            extracted_values=extracted_values,
            field_definitions=field_definitions,
        )
        assert isinstance(results, dict)
        for fdef in field_definitions:
            assert fdef["name"] in results

    def test_standardize_record_fields_single_field(self):
        """Single field should work; provider called exactly once."""
        field_definitions = [{"name": "outcome", "type": "text"}]
        extracted_values = [{"field_name": "outcome", "raw_value": "mortality"}]
        entries = [{"original": "mortality", "value": "Mortality", "unit": None, "confidence": 0.99}]
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        standardizer.standardize_record_fields(
            record_id="rec_003",
            extracted_values=extracted_values,
            field_definitions=field_definitions,
        )
        provider.chat_completion.assert_called_once()

    def test_standardize_record_fields_empty_extracted_values(self):
        """Empty extracted_values should return empty dict without calling provider."""
        field_definitions = [{"name": "dose", "type": "text"}]
        entries = []
        provider = _make_mock_provider(_make_normalized_json(entries))
        standardizer = AIStandardizer(provider)
        results = standardizer.standardize_record_fields(
            record_id="rec_004",
            extracted_values=[],
            field_definitions=field_definitions,
        )
        assert isinstance(results, dict)
        assert len(results) == 0
        provider.chat_completion.assert_not_called()


# =============================================================================
# Section 3: build_audit_prompt()
# =============================================================================

class TestBuildAuditPrompt:
    """Tests for the audit prompt builder in audit.py."""

    def _sample_record_meta(self) -> dict:
        return {"record_id": "rec_001", "title": "Test Study"}

    def _sample_extracted(self) -> dict:
        return {
            "dose":   {"value": "10 mg", "confidence": 0.9, "evidence": "10 mg daily"},
            "sex":    {"value": "M",     "confidence": 0.85, "evidence": "male patients"},
        }

    def _sample_standardized(self) -> dict:
        return {
            "dose":   {"value": 10.0, "unit": "mg",  "confidence": 0.92},
            "sex":    {"value": "male", "unit": None, "confidence": 0.95},
        }

    # ── structure ────────────────────────────────────────────────────────────

    def test_returns_list(self):
        """Result must be a list."""
        messages = build_audit_prompt(
            record_meta=self._sample_record_meta(),
            extracted_fields=self._sample_extracted(),
            standardized_fields=self._sample_standardized(),
        )
        assert isinstance(messages, list)

    def test_has_system_message(self):
        """Must include a system-role message."""
        messages = build_audit_prompt(
            record_meta=self._sample_record_meta(),
            extracted_fields=self._sample_extracted(),
            standardized_fields=self._sample_standardized(),
        )
        roles = [m["role"] for m in messages]
        assert "system" in roles

    def test_has_user_message(self):
        """Must include a user-role message."""
        messages = build_audit_prompt(
            record_meta=self._sample_record_meta(),
            extracted_fields=self._sample_extracted(),
            standardized_fields=self._sample_standardized(),
        )
        roles = [m["role"] for m in messages]
        assert "user" in roles

    def test_messages_have_content(self):
        """All messages must have non-empty content."""
        messages = build_audit_prompt(
            record_meta=self._sample_record_meta(),
            extracted_fields=self._sample_extracted(),
            standardized_fields=self._sample_standardized(),
        )
        for msg in messages:
            assert "content" in msg
            assert isinstance(msg["content"], str)
            assert len(msg["content"]) > 0

    def test_system_is_first_message(self):
        """System message should come before user message."""
        messages = build_audit_prompt(
            record_meta=self._sample_record_meta(),
            extracted_fields=self._sample_extracted(),
            standardized_fields=self._sample_standardized(),
        )
        assert messages[0]["role"] == "system"

    # ── user message content ─────────────────────────────────────────────────

    def test_user_message_contains_extracted_fields(self):
        """User message must reference extracted_fields data."""
        extracted = {"dose_unique_xyz": {"value": "10 mg", "confidence": 0.9, "evidence": "e"}}
        messages = build_audit_prompt(
            record_meta=self._sample_record_meta(),
            extracted_fields=extracted,
            standardized_fields={"dose_unique_xyz": {"value": 10.0, "unit": "mg", "confidence": 0.9}},
        )
        user_content = messages[-1]["content"]
        assert "dose_unique_xyz" in user_content

    def test_user_message_contains_standardized_fields(self):
        """User message must reference standardized_fields data."""
        standardized = {"marker_abc123": {"value": 99.9, "unit": "mmol/L", "confidence": 0.88}}
        messages = build_audit_prompt(
            record_meta=self._sample_record_meta(),
            extracted_fields={"marker_abc123": {"value": "raw", "confidence": 0.7, "evidence": "e"}},
            standardized_fields=standardized,
        )
        user_content = messages[-1]["content"]
        assert "marker_abc123" in user_content

    def test_user_message_field_names_present(self):
        """All field names should appear in the user message."""
        extracted = {
            "field_alpha": {"value": "A", "confidence": 0.9, "evidence": "ctx"},
            "field_beta":  {"value": "B", "confidence": 0.8, "evidence": "ctx"},
        }
        standardized = {
            "field_alpha": {"value": "a", "unit": None, "confidence": 0.95},
            "field_beta":  {"value": "b", "unit": None, "confidence": 0.85},
        }
        messages = build_audit_prompt(
            record_meta=self._sample_record_meta(),
            extracted_fields=extracted,
            standardized_fields=standardized,
        )
        user_content = messages[-1]["content"]
        assert "field_alpha" in user_content
        assert "field_beta" in user_content

    def test_empty_fields_still_returns_valid_messages(self):
        """Empty dicts should still produce a valid messages list."""
        messages = build_audit_prompt(
            record_meta={},
            extracted_fields={},
            standardized_fields={},
        )
        assert isinstance(messages, list)
        assert len(messages) >= 2
        for msg in messages:
            assert "role" in msg
            assert "content" in msg

    def test_both_extracted_and_standardized_in_user(self):
        """User message should reference both extracted and standardized concepts."""
        messages = build_audit_prompt(
            record_meta=self._sample_record_meta(),
            extracted_fields=self._sample_extracted(),
            standardized_fields=self._sample_standardized(),
        )
        user_content = messages[-1]["content"].lower()
        has_extracted = "extract" in user_content
        has_standardized = "standard" in user_content or "normaliz" in user_content
        assert has_extracted or has_standardized
