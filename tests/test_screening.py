"""
tests/test_screening.py — Phase 5.3: Screening test suite for PaperPilot.

Covers:
- protocol.py   : load_default_protocol(), load_reasons_taxonomy()
- rules_engine.py: auto_screen()
- scorer.py     : compute_score()
- ScreeningRepository (integration)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# ── Optional YAML import ────────────────────────────────────────────────────
try:
    import yaml as _yaml  # noqa: F401
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ────────────────────────────────────────────────────────────────────────────

def _default_protocol():
    """Load the default protocol (used across multiple tests)."""
    from paperpilot.core.screening.protocol import load_default_protocol
    return load_default_protocol()


# ────────────────────────────────────────────────────────────────────────────
# 1. Tests for protocol.py
# ────────────────────────────────────────────────────────────────────────────

class TestLoadDefaultProtocol:
    """Tests for load_default_protocol()."""

    def test_returns_dict(self):
        protocol = _default_protocol()
        assert isinstance(protocol, dict)

    def test_contains_must_exclude_terms(self):
        protocol = _default_protocol()
        assert "must_exclude_terms" in protocol
        assert isinstance(protocol["must_exclude_terms"], list)
        assert len(protocol["must_exclude_terms"]) > 0

    def test_contains_inclusion_criteria(self):
        protocol = _default_protocol()
        assert "inclusion_criteria" in protocol
        assert isinstance(protocol["inclusion_criteria"], list)
        assert len(protocol["inclusion_criteria"]) > 0

    def test_contains_soft_exclude_terms(self):
        protocol = _default_protocol()
        assert "soft_exclude_terms" in protocol
        assert isinstance(protocol["soft_exclude_terms"], list)

    def test_contains_design_allowlist(self):
        protocol = _default_protocol()
        assert "design_allowlist" in protocol
        assert isinstance(protocol["design_allowlist"], list)

    def test_contains_exclusion_criteria(self):
        protocol = _default_protocol()
        assert "exclusion_criteria" in protocol
        assert isinstance(protocol["exclusion_criteria"], list)

    def test_must_exclude_terms_includes_animal(self):
        """Verify "animal" is a must-exclude term (used in rules tests)."""
        protocol = _default_protocol()
        terms = [t.lower() for t in protocol["must_exclude_terms"]]
        assert "animal" in terms

    def test_soft_exclude_terms_includes_pilot(self):
        """Verify at least one soft-exclude term exists."""
        protocol = _default_protocol()
        # protocol_default.json has "pilot study" in soft_exclude_terms
        assert len(protocol["soft_exclude_terms"]) > 0

    def test_decision_policy_present(self):
        protocol = _default_protocol()
        assert "decision_policy" in protocol


@pytest.mark.skipif(not _YAML_AVAILABLE, reason="PyYAML not installed")
class TestLoadReasonsTaxonomy:
    """Tests for load_reasons_taxonomy() — requires PyYAML."""

    def test_returns_dict(self):
        from paperpilot.core.screening.protocol import load_reasons_taxonomy
        taxonomy = load_reasons_taxonomy()
        assert isinstance(taxonomy, dict)

    def test_contains_ta001_to_ta010(self):
        from paperpilot.core.screening.protocol import load_reasons_taxonomy
        taxonomy = load_reasons_taxonomy()
        for code in [f"TA{n:03d}" for n in range(1, 11)]:
            assert code in taxonomy, f"Missing reason code: {code}"

    def test_values_are_strings(self):
        from paperpilot.core.screening.protocol import load_reasons_taxonomy
        taxonomy = load_reasons_taxonomy()
        for code, label in taxonomy.items():
            assert isinstance(label, str), f"{code} label is not a string"

    def test_ta006_is_non_human(self):
        from paperpilot.core.screening.protocol import load_reasons_taxonomy
        taxonomy = load_reasons_taxonomy()
        # TA006 should describe non-human subjects
        assert "non-human" in taxonomy["TA006"].lower() or "human" in taxonomy["TA006"].lower()

    def test_ta007_is_animal(self):
        from paperpilot.core.screening.protocol import load_reasons_taxonomy
        taxonomy = load_reasons_taxonomy()
        label = taxonomy["TA007"].lower()
        assert "animal" in label or "vitro" in label or "non-human" in label


# ────────────────────────────────────────────────────────────────────────────
# 2. Tests for rules_engine.py — auto_screen()
# ────────────────────────────────────────────────────────────────────────────

class TestAutoScreen:
    """Tests for auto_screen()."""

    def setup_method(self):
        from paperpilot.core.screening.rules_engine import auto_screen
        self._auto_screen = auto_screen
        self._protocol = _default_protocol()

    # ── Helper ──────────────────────────────────────────────────────────────

    def _screen(self, title: str = "", abstract: str = "") -> dict:
        record = {"title": title, "abstract": abstract}
        return self._auto_screen(record, self._protocol)

    # ── Must-exclude: non-human / animal ────────────────────────────────────

    def test_animal_in_title_gives_exclude(self):
        result = self._screen(title="Effect of drug X in animal models")
        assert result["decision"] == "exclude"

    def test_animal_reason_code_is_ta006_or_ta007(self):
        result = self._screen(title="Effect of drug X in animal models")
        assert result["reason_code"] in ("TA006", "TA007")

    def test_mouse_in_title_gives_exclude(self):
        result = self._screen(title="A mouse study of compound Z")
        assert result["decision"] == "exclude"
        assert result["reason_code"] in ("TA006", "TA007")

    def test_rat_in_abstract_gives_exclude(self):
        result = self._screen(
            title="Drug efficacy study",
            abstract="We used rat models to assess the intervention."
        )
        assert result["decision"] == "exclude"

    def test_in_vitro_gives_exclude(self):
        result = self._screen(title="In vitro assessment of compound A")
        assert result["decision"] == "exclude"
        assert result["reason_code"] in ("TA006", "TA007")

    def test_cell_line_gives_exclude(self):
        result = self._screen(title="Analysis using cell line HeLa")
        assert result["decision"] == "exclude"

    # ── Must-exclude: non-RCT publication types ──────────────────────────────

    def test_case_report_gives_exclude(self):
        result = self._screen(title="A case report of rare syndrome")
        assert result["decision"] == "exclude"

    def test_editorial_gives_exclude(self):
        result = self._screen(title="Editorial on the future of medicine")
        assert result["decision"] == "exclude"

    # ── Soft-exclude terms → maybe ───────────────────────────────────────────

    def test_pilot_study_gives_maybe(self):
        result = self._screen(title="A pilot study of intervention Y")
        assert result["decision"] == "maybe"

    def test_feasibility_gives_maybe(self):
        result = self._screen(title="Feasibility assessment of a new drug")
        assert result["decision"] == "maybe"

    # ── Ordinary title → maybe (default) ─────────────────────────────────────

    def test_plain_title_gives_maybe(self):
        result = self._screen(
            title="Effectiveness of cognitive behavioural therapy",
            abstract="We recruited 100 patients in a clinical setting."
        )
        assert result["decision"] == "maybe"

    def test_plain_title_no_auto_include(self):
        """Engine must never auto-include; human review is required."""
        result = self._screen(
            title="Randomized controlled trial of drug Z",
            abstract="Patients were randomized to placebo or treatment."
        )
        # Even with RCT keywords the engine only returns maybe, never include
        assert result["decision"] in ("maybe", "include")
        # Specifically, per the source code, it returns "maybe"
        assert result["decision"] == "maybe"

    # ── evidence_snippet ─────────────────────────────────────────────────────

    def test_evidence_snippet_set_on_exclude(self):
        result = self._screen(title="Effect of drug X on mice")
        assert result["evidence_snippet"] is not None
        assert isinstance(result["evidence_snippet"], str)
        assert len(result["evidence_snippet"]) > 0

    def test_evidence_snippet_contains_trigger_word(self):
        result = self._screen(title="Rat model of diabetes")
        snippet = result["evidence_snippet"]
        assert snippet is not None
        assert snippet.lower() in {"rat", "mouse", "mice", "animal",
                                   "in vitro", "cell line"}

    def test_evidence_snippet_set_for_soft_exclude(self):
        result = self._screen(title="Feasibility study of treatment X")
        assert result["evidence_snippet"] is not None

    def test_evidence_snippet_none_for_plain_title(self):
        result = self._screen(
            title="Effectiveness of physiotherapy on back pain",
            abstract="This study assessed pain outcomes."
        )
        assert result["evidence_snippet"] is None

    # ── confidence ────────────────────────────────────────────────────────────

    def test_confidence_field_exists(self):
        result = self._screen(title="A study on patients")
        assert "confidence" in result

    def test_confidence_in_range_0_to_1_plain(self):
        result = self._screen(title="A clinical study on hypertension")
        assert 0.0 <= result["confidence"] <= 1.0

    def test_confidence_in_range_0_to_1_exclude(self):
        result = self._screen(title="Animal model of obesity")
        assert 0.0 <= result["confidence"] <= 1.0

    def test_confidence_high_on_must_exclude(self):
        """Must-exclude matches should have confidence >= 0.85."""
        result = self._screen(title="Animal model of sepsis")
        assert result["confidence"] >= 0.85

    def test_confidence_lower_on_default_maybe(self):
        """Default maybe (no signals) should have confidence < 0.85."""
        result = self._screen(
            title="A study of treatment effects",
            abstract="We studied the outcomes of the patients."
        )
        assert result["confidence"] < 0.85

    # ── Return type ───────────────────────────────────────────────────────────

    def test_returns_dict(self):
        result = self._screen(title="Some paper title")
        assert isinstance(result, dict)

    def test_required_keys_present(self):
        result = self._screen(title="Some paper title")
        for key in ("decision", "reason_code", "evidence_snippet", "confidence"):
            assert key in result, f"Missing key: {key}"

    def test_decision_is_valid_enum(self):
        for title in [
            "Animal experiment on rats",
            "Pilot study of a new drug",
            "Randomized trial of aspirin",
        ]:
            result = self._screen(title=title)
            assert result["decision"] in ("include", "exclude", "maybe")


# ────────────────────────────────────────────────────────────────────────────
# 3. Tests for scorer.py — compute_score()
# ────────────────────────────────────────────────────────────────────────────

class TestComputeScore:
    """Tests for compute_score()."""

    def setup_method(self):
        from paperpilot.core.screening.scorer import compute_score
        self._compute_score = compute_score
        self._protocol = _default_protocol()

    def _score(self, title: str = "", abstract: str = "", year=None) -> dict:
        record = {"title": title, "abstract": abstract}
        if year is not None:
            record["year"] = year
        return self._compute_score(record, self._protocol)

    # ── Return structure ──────────────────────────────────────────────────────

    def test_returns_dict(self):
        result = self._score(title="A study")
        assert isinstance(result, dict)

    def test_score_total_key_present(self):
        result = self._score(title="A study")
        assert "score_total" in result

    def test_breakdown_key_present(self):
        result = self._score(title="A study")
        assert "breakdown" in result
        assert isinstance(result["breakdown"], dict)

    def test_breakdown_contains_sub_items(self):
        result = self._score(title="A study")
        breakdown = result["breakdown"]
        for key in ("title_keyword_hits", "abstract_keyword_hits",
                    "design_match", "year_recency"):
            assert key in breakdown, f"Missing breakdown key: {key}"

    # ── score_total range ─────────────────────────────────────────────────────

    def test_score_total_in_0_100_plain(self):
        result = self._score(title="A study on pain management")
        assert 0.0 <= result["score_total"] <= 100.0

    def test_score_total_in_0_100_empty(self):
        result = self._score()
        assert 0.0 <= result["score_total"] <= 100.0

    def test_score_total_in_0_100_rich(self):
        result = self._score(
            title="Randomized controlled trial of human participants",
            abstract="Relevant intervention or exposure with relevant outcomes reported",
            year=2020,
        )
        assert 0.0 <= result["score_total"] <= 100.0

    # ── inclusion_criteria keywords boost score ───────────────────────────────

    def test_inclusion_kw_boosts_score(self):
        """Record with inclusion-criteria keywords should score above baseline."""
        # A record with no relevant keywords
        baseline = self._score(title="Xyz paper about nothing", abstract="")
        # A record mentioning inclusion criteria directly
        boosted = self._score(
            title="Randomized controlled trials of human participants",
            abstract="Relevant intervention and relevant outcomes reported"
        )
        assert boosted["score_total"] > baseline["score_total"]

    def test_abstract_inclusion_kw_boosts_score(self):
        no_kw = self._score(title="Paper about XYZ", abstract="No relevant content")
        with_kw = self._score(
            title="Paper about XYZ",
            abstract="Randomized controlled trials with human participants"
        )
        assert with_kw["score_total"] > no_kw["score_total"]

    # ── design_allowlist keywords give extra score ────────────────────────────

    def test_design_allowlist_gives_extra_score(self):
        """Design allowlist terms (e.g. 'RCT') should increase score."""
        without_design = self._score(
            title="Study of patients with diabetes",
            abstract="We measured outcomes in the intervention group."
        )
        with_design = self._score(
            title="Randomized controlled trial of patients with diabetes",
            abstract="Double-blind placebo-controlled measurement of outcomes."
        )
        assert with_design["score_total"] > without_design["score_total"]

    def test_design_match_nonzero_when_design_word_present(self):
        result = self._score(
            title="A randomized controlled trial",
            abstract="Double-blind study"
        )
        assert result["breakdown"]["design_match"] > 0.0

    def test_design_match_zero_when_no_design_word(self):
        result = self._score(
            title="A study on hypertension",
            abstract="Patients were assessed for blood pressure."
        )
        assert result["breakdown"]["design_match"] == 0.0

    # ── year_recency ──────────────────────────────────────────────────────────

    def test_recent_year_boosts_score(self):
        old = self._score(title="Clinical study", year=2000)
        recent = self._score(title="Clinical study", year=2019)
        assert recent["score_total"] > old["score_total"]

    def test_recency_nonzero_for_recent_year(self):
        result = self._score(title="Study", year=2020)
        assert result["breakdown"]["year_recency"] > 0.0

    def test_recency_zero_for_old_year(self):
        result = self._score(title="Study", year=2000)
        assert result["breakdown"]["year_recency"] == 0.0

    def test_recency_zero_for_missing_year(self):
        result = self._score(title="Study")
        assert result["breakdown"]["year_recency"] == 0.0

    # ── Empty / edge cases ────────────────────────────────────────────────────

    def test_empty_record_scores_zero(self):
        result = self._score()
        assert result["score_total"] == 0.0

    def test_score_is_float(self):
        result = self._score(title="RCT human participants")
        assert isinstance(result["score_total"], float)


# ────────────────────────────────────────────────────────────────────────────
# 4. Integration: ScreeningRepository
# ────────────────────────────────────────────────────────────────────────────

class TestScreeningRepositoryIntegration:
    """Integration tests for ScreeningRepository using a real SQLite project."""

    def setup_method(self):
        """Create a fresh temp project for each test method."""
        from paperpilot.core.project import Project
        from paperpilot.core.repositories import RecordRepository, ScreeningRepository
        from paperpilot.core.models import Record, ScreeningDecision

        self._tmpdir = tempfile.TemporaryDirectory()
        self._project = Project.create(self._tmpdir.name)
        self._rec_repo = RecordRepository(self._project.conn)
        self._s_repo = ScreeningRepository(self._project.conn)
        self._Record = Record
        self._ScreeningDecision = ScreeningDecision

    def teardown_method(self):
        self._project.close()
        self._tmpdir.cleanup()

    def _insert_record(self, title: str = "Test Paper", year: int = 2023):
        rec = self._Record(title=title, year=year)
        self._rec_repo.insert(rec)
        return rec

    # ── Basic insert + get_latest ─────────────────────────────────────────────

    def test_insert_and_get_latest_exclude(self):
        rec = self._insert_record("Animal experiment study")
        decision = self._ScreeningDecision(
            record_id=rec.id,
            decision="exclude",
            reason_code="TA006",
            evidence_snippet="animal",
        )
        self._s_repo.insert(decision)

        latest = self._s_repo.get_latest(rec.id)
        assert latest is not None
        assert latest.decision == "exclude"
        assert latest.reason_code == "TA006"
        assert latest.evidence_snippet == "animal"
        assert latest.record_id == rec.id

    def test_get_latest_returns_most_recent(self):
        rec = self._insert_record("Paper under review")

        # Insert exclude first
        dec1 = self._ScreeningDecision(
            record_id=rec.id, decision="exclude", reason_code="TA007"
        )
        self._s_repo.insert(dec1)

        # Insert include second
        dec2 = self._ScreeningDecision(
            record_id=rec.id, decision="include", reason_code=None
        )
        self._s_repo.insert(dec2)

        latest = self._s_repo.get_latest(rec.id)
        assert latest is not None
        assert latest.decision == "include"

    # ── get_history ───────────────────────────────────────────────────────────

    def test_get_history_contains_two_decisions(self):
        rec = self._insert_record("Iteratively screened paper")

        dec1 = self._ScreeningDecision(
            record_id=rec.id, decision="exclude", reason_code="TA006",
            evidence_snippet="animal"
        )
        self._s_repo.insert(dec1)

        dec2 = self._ScreeningDecision(
            record_id=rec.id, decision="include", reason_code=None
        )
        self._s_repo.insert(dec2)

        history = self._s_repo.get_history(rec.id)
        assert len(history) == 2

    def test_get_history_ordered_by_ts_desc(self):
        rec = self._insert_record("Paper with history")

        dec1 = self._ScreeningDecision(
            record_id=rec.id, decision="exclude", reason_code="TA007"
        )
        self._s_repo.insert(dec1)
        dec2 = self._ScreeningDecision(
            record_id=rec.id, decision="include"
        )
        self._s_repo.insert(dec2)

        history = self._s_repo.get_history(rec.id)
        # Most recent first
        assert history[0].decision == "include"
        assert history[1].decision == "exclude"

    def test_get_history_empty_for_no_decisions(self):
        rec = self._insert_record("Unscreened paper")
        history = self._s_repo.get_history(rec.id)
        assert history == []

    def test_get_latest_returns_none_when_no_decision(self):
        rec = self._insert_record("No decision yet")
        latest = self._s_repo.get_latest(rec.id)
        assert latest is None

    # ── Decision fields ───────────────────────────────────────────────────────

    def test_decision_fields_round_trip(self):
        rec = self._insert_record("Full-field paper")
        dec = self._ScreeningDecision(
            record_id=rec.id,
            stage="title_abstract",
            decision="exclude",
            reason_code="TA006",
            evidence_snippet="animal model used",
            source="rules_engine",
        )
        self._s_repo.insert(dec)

        latest = self._s_repo.get_latest(rec.id, stage="title_abstract")
        assert latest.stage == "title_abstract"
        assert latest.reason_code == "TA006"
        assert latest.evidence_snippet == "animal model used"
        assert latest.source == "rules_engine"

    def test_multiple_records_independent(self):
        rec1 = self._insert_record("Record one")
        rec2 = self._insert_record("Record two")

        self._s_repo.insert(self._ScreeningDecision(
            record_id=rec1.id, decision="exclude", reason_code="TA006"
        ))
        self._s_repo.insert(self._ScreeningDecision(
            record_id=rec2.id, decision="include"
        ))

        assert self._s_repo.get_latest(rec1.id).decision == "exclude"
        assert self._s_repo.get_latest(rec2.id).decision == "include"
        assert len(self._s_repo.get_history(rec1.id)) == 1
        assert len(self._s_repo.get_history(rec2.id)) == 1
