# tests/test_meta.py - Tests for meta-analysis data prep and R runner
import unittest
import json
import subprocess
import tempfile
import os
from unittest.mock import patch, MagicMock


class TestPrepareMetaData(unittest.TestCase):
    def setUp(self):
        from paperpilot.core.meta.data_prep import prepare_meta_data
        self.prepare = prepare_meta_data

    def _make_extracted(self, record_id, yi=None, vi=None, se=None, ni=None, group=None):
        values = []
        if yi is not None:
            values.append({"field_name": "effect_size", "value": str(yi), "confidence": 0.9})
        if vi is not None:
            values.append({"field_name": "variance", "value": str(vi), "confidence": 0.9})
        if se is not None:
            values.append({"field_name": "standard_error", "value": str(se), "confidence": 0.9})
        if ni is not None:
            values.append({"field_name": "sample_size", "value": str(ni), "confidence": 0.9})
        if group is not None:
            values.append({"field_name": "subgroup", "value": str(group), "confidence": 0.9})
        return {record_id: values}

    def test_basic_yi_vi(self):
        extracted = {}
        for i in range(3):
            rid = f"r{i}"
            extracted[rid] = [
                {"field_name": "effect_size", "value": str(0.5 + i * 0.1), "confidence": 0.9},
                {"field_name": "variance", "value": "0.01", "confidence": 0.9},
            ]
        result = self.prepare(extracted, outcome_field="effect_size", se_field=None)
        self.assertEqual(result["n_valid"], 3)
        self.assertEqual(result["n_missing"], 0)
        self.assertEqual(len(result["data"]), 3)
        for row in result["data"]:
            self.assertIn("yi", row)
            self.assertIn("vi", row)
            self.assertIsInstance(row["yi"], float)

    def test_se_converted_to_vi(self):
        """SE field should be converted to variance (vi = se^2)"""
        extracted = {}
        for i in range(3):
            rid = f"r{i}"
            extracted[rid] = [
                {"field_name": "effect_size", "value": "0.5", "confidence": 0.9},
                {"field_name": "standard_error", "value": "0.1", "confidence": 0.9},
            ]
        result = self.prepare(
            extracted, outcome_field="effect_size", se_field="standard_error"
        )
        self.assertEqual(result["n_valid"], 3)
        for row in result["data"]:
            self.assertAlmostEqual(row["vi"], 0.01, places=4)

    def test_missing_yi_counted(self):
        extracted = {
            "r0": [{"field_name": "variance", "value": "0.01", "confidence": 0.9}],
            "r1": [
                {"field_name": "effect_size", "value": "0.5", "confidence": 0.9},
                {"field_name": "variance", "value": "0.01", "confidence": 0.9},
            ],
        }
        result = self.prepare(extracted, outcome_field="effect_size")
        self.assertEqual(result["n_missing"], 1)
        self.assertEqual(result["n_valid"], 1)

    def test_group_field(self):
        extracted = {}
        for i, grp in enumerate(["A", "B", "A"]):
            rid = f"r{i}"
            extracted[rid] = [
                {"field_name": "effect_size", "value": "0.5", "confidence": 0.9},
                {"field_name": "variance", "value": "0.01", "confidence": 0.9},
                {"field_name": "subgroup", "value": grp, "confidence": 0.9},
            ]
        result = self.prepare(
            extracted, outcome_field="effect_size", group_field="subgroup"
        )
        groups = [row.get("group") for row in result["data"]]
        self.assertIn("A", groups)
        self.assertIn("B", groups)

    def test_non_numeric_yi_counted_as_missing(self):
        extracted = {
            "r0": [
                {"field_name": "effect_size", "value": "not_a_number", "confidence": 0.9},
                {"field_name": "variance", "value": "0.01", "confidence": 0.9},
            ]
        }
        result = self.prepare(extracted, outcome_field="effect_size")
        self.assertEqual(result["n_valid"], 0)
        self.assertTrue(len(result["errors"]) > 0)

    def test_result_has_record_id(self):
        extracted = {
            "abc-123": [
                {"field_name": "effect_size", "value": "0.5", "confidence": 0.9},
                {"field_name": "variance", "value": "0.01", "confidence": 0.9},
            ]
        }
        result = self.prepare(extracted, outcome_field="effect_size")
        self.assertEqual(result["data"][0]["record_id"], "abc-123")


class TestValidateMetaData(unittest.TestCase):
    def setUp(self):
        from paperpilot.core.meta.data_prep import validate_meta_data
        self.validate = validate_meta_data

    def _make_data(self, n=3, yi=0.5, vi=0.01):
        return [{"record_id": f"r{i}", "yi": yi, "vi": vi, "ni": None, "group": None}
                for i in range(n)]

    def test_valid_data(self):
        ok, errors = self.validate(self._make_data(5))
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_too_few_records(self):
        ok, errors = self.validate(self._make_data(2))
        self.assertFalse(ok)
        self.assertTrue(any("3" in e for e in errors))

    def test_zero_variance_invalid(self):
        data = self._make_data(3)
        data[0]["vi"] = 0.0
        ok, errors = self.validate(data)
        self.assertFalse(ok)

    def test_negative_variance_invalid(self):
        data = self._make_data(3)
        data[1]["vi"] = -0.01
        ok, errors = self.validate(data)
        self.assertFalse(ok)

    def test_none_yi_invalid(self):
        data = self._make_data(3)
        data[0]["yi"] = None
        ok, errors = self.validate(data)
        self.assertFalse(ok)

    def test_empty_list(self):
        ok, errors = self.validate([])
        self.assertFalse(ok)


class TestMetaRunnerAvailability(unittest.TestCase):
    def setUp(self):
        from paperpilot.core.meta.runner import MetaRunner
        self.MetaRunner = MetaRunner

    def test_r_not_available_fake_path(self):
        runner = self.MetaRunner(r_executable="/nonexistent/Rscript")
        self.assertFalse(runner.is_r_available())

    def test_r_check_uses_executable(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError
            runner = self.MetaRunner(r_executable="Rscript")
            result = runner.is_r_available()
            self.assertFalse(result)

    def test_r_available_when_subprocess_succeeds(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            runner = self.MetaRunner(r_executable="Rscript")
            self.assertTrue(runner.is_r_available())


class TestMetaRunnerBuildScript(unittest.TestCase):
    def setUp(self):
        from paperpilot.core.meta.runner import MetaRunner
        self.runner = MetaRunner()

    def test_script_contains_metafor(self):
        data = [{"yi": 0.5, "vi": 0.01, "record_id": "r0", "ni": None, "group": None}]
        script = self.runner._build_r_script(data, "REML")
        self.assertIn("metafor", script)

    def test_script_contains_method(self):
        data = [{"yi": 0.5, "vi": 0.01, "record_id": "r0", "ni": None, "group": None}]
        script = self.runner._build_r_script(data, "DL")
        self.assertIn("DL", script)

    def test_script_contains_yi_values(self):
        data = [
            {"yi": 0.5, "vi": 0.01, "record_id": "r0", "ni": None, "group": None},
            {"yi": 0.3, "vi": 0.02, "record_id": "r1", "ni": None, "group": None},
        ]
        script = self.runner._build_r_script(data, "REML")
        self.assertIn("0.5", script)
        self.assertIn("0.3", script)

    def test_script_is_string(self):
        data = [{"yi": 0.5, "vi": 0.01, "record_id": "r0", "ni": None, "group": None}]
        script = self.runner._build_r_script(data, "REML")
        self.assertIsInstance(script, str)


class TestMetaRunnerRunRandomEffects(unittest.TestCase):
    def setUp(self):
        from paperpilot.core.meta.runner import MetaRunner
        self.MetaRunner = MetaRunner

    def test_r_not_available_raises_or_returns_error(self):
        runner = self.MetaRunner(r_executable="/nonexistent/Rscript")
        data = [
            {"yi": 0.5, "vi": 0.01, "record_id": "r0", "ni": None, "group": None},
            {"yi": 0.3, "vi": 0.02, "record_id": "r1", "ni": None, "group": None},
            {"yi": 0.4, "vi": 0.015, "record_id": "r2", "ni": None, "group": None},
        ]
        try:
            result = runner.run_random_effects(data)
            # If it returns a dict, it should have an "error" key
            self.assertIn("error", result)
        except (RuntimeError, FileNotFoundError):
            pass  # Also acceptable

    def test_mock_r_success(self):
        mock_output = json.dumps({
            "estimate": 0.42,
            "se": 0.08,
            "ci_lower": 0.26,
            "ci_upper": 0.58,
            "I2": 35.2,
            "tau2": 0.012,
            "Q": 4.3,
            "Q_pval": 0.12,
            "k": 3,
            "method": "REML"
        })

        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = mock_output
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            runner = self.MetaRunner()
            # Override is_r_available to return True
            with patch.object(runner, "is_r_available", return_value=True):
                data = [
                    {"yi": 0.5, "vi": 0.01, "record_id": "r0", "ni": None, "group": None},
                    {"yi": 0.3, "vi": 0.02, "record_id": "r1", "ni": None, "group": None},
                    {"yi": 0.4, "vi": 0.015, "record_id": "r2", "ni": None, "group": None},
                ]
                result = runner.run_random_effects(data)
            self.assertIn("estimate", result)
            self.assertAlmostEqual(result["estimate"], 0.42, places=2)
            self.assertIn("I2", result)
            self.assertIn("k", result)

    def test_required_output_keys(self):
        mock_output = json.dumps({
            "estimate": 0.3, "se": 0.05, "ci_lower": 0.2, "ci_upper": 0.4,
            "I2": 20.0, "tau2": 0.005, "Q": 2.1, "Q_pval": 0.35, "k": 3, "method": "REML"
        })
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = mock_output
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            runner = self.MetaRunner()
            with patch.object(runner, "is_r_available", return_value=True):
                data = [{"yi": 0.5, "vi": 0.01, "record_id": f"r{i}", "ni": None, "group": None}
                        for i in range(3)]
                result = runner.run_random_effects(data)

            for key in ["estimate", "se", "ci_lower", "ci_upper", "I2", "tau2", "Q", "Q_pval", "k"]:
                self.assertIn(key, result)


class TestMetaRunnerSubgroup(unittest.TestCase):
    def setUp(self):
        from paperpilot.core.meta.runner import MetaRunner
        self.MetaRunner = MetaRunner

    def test_subgroup_splits_by_group(self):
        mock_output = json.dumps({
            "estimate": 0.4, "se": 0.06, "ci_lower": 0.28, "ci_upper": 0.52,
            "I2": 10.0, "tau2": 0.003, "Q": 1.5, "Q_pval": 0.47, "k": 2, "method": "REML"
        })
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = mock_output
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            runner = self.MetaRunner()
            with patch.object(runner, "is_r_available", return_value=True):
                data = [
                    {"yi": 0.5, "vi": 0.01, "record_id": "r0", "ni": None, "group": "A"},
                    {"yi": 0.6, "vi": 0.02, "record_id": "r1", "ni": None, "group": "A"},
                    {"yi": 0.2, "vi": 0.01, "record_id": "r2", "ni": None, "group": "B"},
                    {"yi": 0.3, "vi": 0.02, "record_id": "r3", "ni": None, "group": "B"},
                ]
                result = runner.run_subgroup(data)
            self.assertIn("A", result)
            self.assertIn("B", result)
            self.assertIn("estimate", result["A"])


if __name__ == "__main__":
    unittest.main()
