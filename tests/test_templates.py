"""Tests for template files — validates existence and parse correctness."""
import json
import yaml
import csv
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent / "paperpilot" / "assets" / "templates"


def test_protocol_default_json():
    f = TEMPLATES_DIR / "protocol_default.json"
    assert f.exists(), "protocol_default.json not found"
    data = json.loads(f.read_text())
    assert "name" in data
    assert "inclusion_criteria" in data
    assert "exclusion_criteria" in data
    assert "must_exclude_terms" in data
    assert isinstance(data["inclusion_criteria"], list)


def test_reasons_taxonomy_yaml():
    f = TEMPLATES_DIR / "reasons_taxonomy.yaml"
    assert f.exists(), "reasons_taxonomy.yaml not found"
    data = yaml.safe_load(f.read_text())
    assert "exclusion_reasons" in data
    reasons = data["exclusion_reasons"]
    assert "TA001" in reasons
    assert "TA006" in reasons
    for code, reason in reasons.items():
        assert "label" in reason
        assert "description" in reason


def test_extraction_template_meta_json():
    f = TEMPLATES_DIR / "extraction_template_meta.json"
    assert f.exists(), "extraction_template_meta.json not found"
    data = json.loads(f.read_text())
    assert "fields" in data
    assert isinstance(data["fields"], list)
    keys = [field["key"] for field in data["fields"]]
    assert "study_id" in keys
    assert "outcome_name" in keys
    assert "events_t" in keys
    assert "mean_t" in keys


def test_meta_runner_r_exists():
    f = TEMPLATES_DIR / "meta_runner.R"
    assert f.exists(), "meta_runner.R not found"
    content = f.read_text()
    assert "metafor" in content
    assert "rma" in content


def test_sample_meta_binary_csv():
    f = TEMPLATES_DIR / "sample_meta_binary.csv"
    assert f.exists(), "sample_meta_binary.csv not found"
    rows = list(csv.DictReader(f.open()))
    assert len(rows) >= 3
    required = {"study_id", "outcome_name", "events_t", "total_t", "events_c", "total_c"}
    assert required <= set(rows[0].keys())


def test_sample_meta_continuous_csv():
    f = TEMPLATES_DIR / "sample_meta_continuous.csv"
    assert f.exists(), "sample_meta_continuous.csv not found"
    rows = list(csv.DictReader(f.open()))
    assert len(rows) >= 3
    required = {"study_id", "outcome_name", "mean_t", "sd_t", "n_t", "mean_c", "sd_c", "n_c"}
    assert required <= set(rows[0].keys())
