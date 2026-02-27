# tests/test_e2e.py - End-to-end integration tests for PaperPilot workflow
"""
E2E tests simulate a complete systematic review workflow:
  Import CSV -> Dedup -> Screening decision -> Export RIS -> Export Excel

These tests use real SQLite databases in temp directories.
No PySide6 or R required.
"""
import io
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Skip guard: ensure core modules are importable
# ---------------------------------------------------------------------------
try:
    from paperpilot.core.project import Project
    from paperpilot.core.importers.csv import import_csv
    from paperpilot.core.repositories import RecordRepository
    _CORE_AVAILABLE = True
except ImportError as e:
    _CORE_AVAILABLE = False
    _IMPORT_ERROR = str(e)

try:
    from paperpilot.core.dedup import run_dedup
    _DEDUP_AVAILABLE = True
except ImportError:
    _DEDUP_AVAILABLE = False

try:
    from paperpilot.core.exporters.ris import export_ris
    from paperpilot.core.exporters.excel import export_excel
    _EXPORT_AVAILABLE = True
except ImportError:
    _EXPORT_AVAILABLE = False


def _make_csv(rows: list[dict]) -> str:
    """Build a CSV string from list of dicts."""
    if not rows:
        return ""
    headers = list(rows[0].keys())
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(str(row.get(h, "")) for h in headers))
    return "\n".join(lines)


def _sample_records(n: int = 5, add_duplicates: bool = True) -> list[dict]:
    records = []
    for i in range(n):
        records.append({
            "title": f"Effect of intervention {i} on outcome",
            "abstract": f"This randomized controlled trial investigated intervention {i}.",
            "authors": f"Smith J; Jones B",
            "year": str(2018 + i),
            "journal": "Journal of Medicine",
            "doi": f"10.1000/test.{i:04d}",
            "pmid": f"123456{i}",
            "keywords": "RCT; intervention; outcome",
        })
    if add_duplicates and n >= 2:
        # Add an exact duplicate of record 0 (same DOI)
        dup = dict(records[0])
        dup["authors"] = "Smith John; Jones Bob"  # slightly different author string
        records.append(dup)
    return records


@unittest.skipUnless(_CORE_AVAILABLE, f"Core modules not available")
class TestFullWorkflow(unittest.TestCase):
    """Complete workflow: CSV import -> dedup -> screening -> export"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project_dir = os.path.join(self.tmp.name, "test_project")
        os.makedirs(self.project_dir)
        self.project = Project.create(self.project_dir)
        self.repo = RecordRepository(self.project.conn)

    def tearDown(self):
        self.project.conn.close()
        self.tmp.cleanup()

    def _import_sample_csv(self, n=5, add_duplicates=True):
        rows = _sample_records(n, add_duplicates)
        csv_text = _make_csv(rows)
        csv_file = os.path.join(self.tmp.name, "sample.csv")
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write(csv_text)
        records = import_csv(csv_file)
        for rec in records:
            self.repo.create(rec)
        return records

    def test_import_record_count(self):
        """CSV import stores correct number of records."""
        records = self._import_sample_csv(n=5, add_duplicates=True)
        all_records = self.repo.list_all()
        self.assertEqual(len(all_records), 6)  # 5 + 1 duplicate

    def test_import_fields_populated(self):
        """Imported records have title and doi."""
        self._import_sample_csv(n=3, add_duplicates=False)
        records = self.repo.list_all()
        for rec in records:
            self.assertTrue(rec.title, "title should be non-empty")
            self.assertIsNotNone(rec.doi)

    def test_import_title_norm_set(self):
        """title_norm is computed and stored."""
        self._import_sample_csv(n=2, add_duplicates=False)
        records = self.repo.list_all()
        for rec in records:
            self.assertTrue(hasattr(rec, "title_norm"))
            if rec.title_norm:
                self.assertEqual(rec.title_norm, rec.title_norm.lower())

    @unittest.skipUnless(_DEDUP_AVAILABLE, "dedup not available")
    def test_dedup_finds_duplicate(self):
        """Dedup identifies the exact DOI duplicate."""
        self._import_sample_csv(n=5, add_duplicates=True)
        records = self.repo.list_all()
        record_dicts = [r.model_dump() for r in records]
        clusters = run_dedup(record_dicts)
        # Should find at least 1 cluster (the DOI duplicate)
        self.assertGreaterEqual(len(clusters), 1)
        # At least one cluster has 2 members (the duplicate pair)
        multi = [c for c in clusters if len(c.member_ids) >= 2]
        self.assertGreaterEqual(len(multi), 1)

    @unittest.skipUnless(_DEDUP_AVAILABLE, "dedup not available")
    def test_dedup_confidence_for_doi_match(self):
        """DOI duplicates should have confidence=1.0."""
        self._import_sample_csv(n=3, add_duplicates=True)
        records = self.repo.list_all()
        record_dicts = [r.model_dump() for r in records]
        clusters = run_dedup(record_dicts)
        doi_clusters = [c for c in clusters if c.confidence >= 1.0]
        self.assertGreaterEqual(len(doi_clusters), 1)

    def _make_decisions(self):
        """Return {record_id: decision_dict} and {record_id: [history]}."""
        records = self.repo.list_all()
        decisions = {}
        history = {}
        for i, rec in enumerate(records):
            d = "include" if i % 2 == 0 else "exclude"
            decisions[rec.id] = {
                "decision": d,
                "stage": "title_abstract",
                "reason_code": "TA001" if d == "exclude" else None,
                "score": 75.0,
                "updated": "2026-02-27",
            }
            history[rec.id] = [decisions[rec.id]]
        return decisions, history

    @unittest.skipUnless(_EXPORT_AVAILABLE, "exporters not available")
    def test_export_ris_include_filter(self):
        """RIS export with include filter only writes included records."""
        self._import_sample_csv(n=4, add_duplicates=False)
        records = self.repo.list_all()
        decisions, history = self._make_decisions()
        out_path = os.path.join(self.tmp.name, "output.ris")

        result = export_ris(
            [r.model_dump() for r in records],
            decisions,
            history,
            out_path,
            filter_decision="include",
        )
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 0)
        self.assertGreater(result["exported"], 0)
        # Skipped count = exclude records
        self.assertGreater(result["skipped"], 0)

        with open(out_path, encoding="utf-8-sig") as f:
            content = f.read()
        self.assertIn("TY  -", content)
        self.assertIn("RPID:", content)

    @unittest.skipUnless(_EXPORT_AVAILABLE, "exporters not available")
    def test_export_ris_all(self):
        """RIS export with no filter writes all records."""
        self._import_sample_csv(n=3, add_duplicates=False)
        records = self.repo.list_all()
        decisions, history = self._make_decisions()
        out_path = os.path.join(self.tmp.name, "all.ris")
        result = export_ris(
            [r.model_dump() for r in records],
            decisions, history, out_path, filter_decision=None,
        )
        self.assertEqual(result["exported"], len(records))
        self.assertEqual(result["skipped"], 0)

    @unittest.skipUnless(_EXPORT_AVAILABLE, "exporters not available")
    def test_export_excel_creates_file(self):
        """Excel export creates a non-empty .xlsx file."""
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")

        self._import_sample_csv(n=3, add_duplicates=False)
        records = self.repo.list_all()
        decisions, history = self._make_decisions()
        out_path = os.path.join(self.tmp.name, "output.xlsx")
        result = export_excel(
            [r.model_dump() for r in records],
            decisions, history, {}, out_path,
        )
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 1000)
        self.assertIn("sheets", result)


@unittest.skipUnless(_CORE_AVAILABLE, "Core modules not available")
class TestRISRoundtrip(unittest.TestCase):
    """CSV import -> RIS export -> RIS re-import consistency."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project_dir = os.path.join(self.tmp.name, "proj")
        os.makedirs(self.project_dir)
        self.project = Project.create(self.project_dir)
        self.repo = RecordRepository(self.project.conn)

    def tearDown(self):
        self.project.conn.close()
        self.tmp.cleanup()

    @unittest.skipUnless(_EXPORT_AVAILABLE, "exporters not available")
    def test_ris_contains_rpid(self):
        """Exported RIS contains RPID tag for each record."""
        rows = _sample_records(3, add_duplicates=False)
        csv_text = _make_csv(rows)
        csv_file = os.path.join(self.tmp.name, "s.csv")
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write(csv_text)
        records = import_csv(csv_file)
        for r in records:
            self.repo.create(r)

        out_path = os.path.join(self.tmp.name, "out.ris")
        all_recs = self.repo.list_all()
        export_ris([r.model_dump() for r in all_recs], {}, {}, out_path)
        with open(out_path, encoding="utf-8-sig") as f:
            content = f.read()
        rpid_count = content.count("RPID:")
        self.assertEqual(rpid_count, len(all_recs))

    @unittest.skipUnless(_EXPORT_AVAILABLE, "exporters not available")
    def test_ris_reimport_preserves_titles(self):
        """Re-importing exported RIS preserves original titles."""
        try:
            from paperpilot.core.importers.ris import import_ris
        except ImportError:
            self.skipTest("RIS importer not available")

        rows = _sample_records(3, add_duplicates=False)
        csv_text = _make_csv(rows)
        csv_file = os.path.join(self.tmp.name, "s.csv")
        with open(csv_file, "w") as f:
            f.write(csv_text)
        records = import_csv(csv_file)
        for r in records:
            self.repo.create(r)

        out_path = os.path.join(self.tmp.name, "out.ris")
        all_recs = self.repo.list_all()
        original_titles = {r.title for r in all_recs}
        export_ris([r.model_dump() for r in all_recs], {}, {}, out_path)

        reimported, _ = import_ris(out_path)
        reimported_titles = {r.title for r in reimported}
        # All original titles should be in re-imported set
        for title in original_titles:
            self.assertIn(title, reimported_titles)


@unittest.skipUnless(_CORE_AVAILABLE, "Core modules not available")
@unittest.skipUnless(_DEDUP_AVAILABLE, "dedup not available")
class TestDedupClusterConsistency(unittest.TestCase):
    """Dedup produces consistent clusters for known duplicates."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _make_record(self, title, doi, year=2020, author="Smith J"):
        from paperpilot.core.dedup.normalize import normalize_title
        return {
            "id": str(uuid.uuid4()),
            "title": title,
            "title_norm": normalize_title(title),
            "doi": doi,
            "pmid": None,
            "cnki_id": None,
            "year": year,
            "authors": author,
            "abstract": "This is a test abstract.",
            "fingerprint": None,
        }

    def test_exact_doi_duplicates(self):
        """Two pairs of DOI duplicates → exactly 2 clusters."""
        records = [
            self._make_record("Study A on outcome", "10.1000/aaa", 2020, "Smith J"),
            self._make_record("Study A on outcome", "10.1000/aaa", 2020, "Smith John"),
            self._make_record("Study B intervention", "10.1000/bbb", 2021, "Jones B"),
            self._make_record("Study B intervention", "10.1000/bbb", 2021, "Jones Bob"),
        ]
        clusters = run_dedup(records)
        self.assertEqual(len(clusters), 2)

    def test_each_cluster_has_two_members(self):
        """Each DOI duplicate cluster has exactly 2 members."""
        records = [
            self._make_record("Study A", "10.1000/aaa"),
            self._make_record("Study A copy", "10.1000/aaa"),
            self._make_record("Study B", "10.1000/bbb"),
            self._make_record("Study B copy", "10.1000/bbb"),
        ]
        clusters = run_dedup(records)
        for c in clusters:
            self.assertEqual(len(c.member_ids), 2)

    def test_unique_records_no_clusters(self):
        """Records with different DOIs should not be clustered."""
        records = [
            self._make_record(f"Unique Study {i}", f"10.1000/unique{i}", 2020 + i)
            for i in range(5)
        ]
        clusters = run_dedup(records)
        self.assertEqual(len(clusters), 0)

    def test_cluster_has_canonical(self):
        """Each cluster has a canonical_record_id that is a member."""
        records = [
            self._make_record("Duplicate", "10.1000/dup"),
            self._make_record("Duplicate", "10.1000/dup"),
        ]
        clusters = run_dedup(records)
        self.assertEqual(len(clusters), 1)
        c = clusters[0]
        self.assertIn(c.canonical_record_id, c.member_ids)


if __name__ == "__main__":
    unittest.main()
