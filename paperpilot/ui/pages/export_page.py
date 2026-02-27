"""
ui/pages/export_page.py — Export page for PaperPilot (Phase 6.3)

Layout:
  Top    : Project statistics summary (read-only)
  Middle : Export options (RIS / Excel) in QGroupBox
  Bottom : Export log (QTextEdit, read-only)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QCheckBox, QComboBox,
    QGroupBox, QTextEdit, QFileDialog, QMessageBox,
    QSizePolicy,
)

# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class _ExportWorker(QObject):
    """Runs the actual export in a background QThread."""

    finished = Signal(str, int)   # (file_path, record_count)
    error    = Signal(str)        # error message

    def __init__(self, kind: str, kwargs: dict):
        super().__init__()
        self._kind   = kind    # "ris" or "excel"
        self._kwargs = kwargs  # arguments forwarded to exporter

    def run(self) -> None:
        try:
            if self._kind == "ris":
                from paperpilot.core.exporters.ris import export_ris
                result = export_ris(**self._kwargs)
                count  = result.get("count", 0)

            elif self._kind == "excel":
                from paperpilot.core.exporters.excel import export_excel
                result = export_excel(**self._kwargs)
                count  = result.get("rows", 0)

            else:
                raise ValueError(f"Unknown export kind: {self._kind!r}")

            self.finished.emit(self._kwargs["out_path"], count)

        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# ExportPage
# ---------------------------------------------------------------------------

class ExportPage(QWidget):
    """Export page: statistics summary + RIS/Excel options + export log."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None

        # State
        self._records:          list[dict] = []
        self._decisions:        dict[str, dict] = {}
        self._decision_history: dict[str, list[dict]] = {}
        self._extracted_values: dict[str, list[dict]] = {}
        self._last_export_time: Optional[str] = None

        # Threading
        self._thread: Optional[QThread]      = None
        self._worker: Optional[_ExportWorker] = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        """Called by the main window when the active project changes."""
        self._project = project
        self._load_data()
        self._refresh_stats()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self) -> None:
        """Load all records, decisions, history and extractions from DB."""
        if self._project is None:
            return

        try:
            from paperpilot.core.repositories import (
                RecordRepository,
                ScreeningRepository,
                ExtractedValueRepository,
            )

            conn = self._project.conn
            rec_repo    = RecordRepository(conn)
            scr_repo    = ScreeningRepository(conn)
            ext_repo    = ExtractedValueRepository(conn)

            db_records = rec_repo.list_all()

            # Convert to plain dicts for the exporters
            self._records = [r.model_dump() for r in db_records]

            # Build decisions map: record_id -> latest decision dict
            self._decisions = {}
            self._decision_history = {}
            for rec in db_records:
                latest = scr_repo.get_latest(rec.id)
                if latest:
                    self._decisions[rec.id] = latest.model_dump()
                history = scr_repo.get_history(rec.id)
                self._decision_history[rec.id] = [h.model_dump() for h in history]

            # Build extracted values map: record_id -> list of dicts
            self._extracted_values = {}
            for rec in db_records:
                evs = ext_repo.get_for_record(rec.id)
                self._extracted_values[rec.id] = [e.model_dump() for e in evs]

        except Exception as exc:  # noqa: BLE001
            self._log(f"[WARN] Could not load project data: {exc}")

    # ------------------------------------------------------------------
    # Statistics helpers
    # ------------------------------------------------------------------

    def _count_decisions(self) -> dict[str, int]:
        total     = len(self._records)
        counts    = {"include": 0, "exclude": 0, "maybe": 0, "undecided": 0}
        for rec in self._records:
            rid = rec.get("id", "")
            dec = self._decisions.get(rid, {})
            val = (dec.get("decision") or "undecided").lower()
            if val in counts:
                counts[val] += 1
            else:
                counts["undecided"] += 1
        counts["total"] = total
        return counts

    def _refresh_stats(self) -> None:
        c = self._count_decisions()
        self._lbl_total.setText(str(c["total"]))
        self._lbl_include.setText(str(c["include"]))
        self._lbl_exclude.setText(str(c["exclude"]))
        self._lbl_maybe.setText(str(c["maybe"]))
        self._lbl_undecided.setText(str(c["undecided"]))
        self._lbl_last_export.setText(self._last_export_time or "—")

    # ------------------------------------------------------------------
    # Record filtering
    # ------------------------------------------------------------------

    def _filtered_records(self, filter_mode: str) -> list[dict]:
        """Return records matching the selected filter mode."""
        mode = filter_mode.lower()
        if mode == "all":
            return list(self._records)

        # Derive target decision
        target_map = {
            "include only": "include",
            "exclude only": "exclude",
            "maybe only":   "maybe",
        }
        target = target_map.get(mode)
        if target is None:
            return list(self._records)

        result = []
        for rec in self._records:
            rid = rec.get("id", "")
            dec = self._decisions.get(rid, {})
            val = (dec.get("decision") or "undecided").lower()
            if val == target:
                result.append(rec)
        return result

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(self._build_stats_box())
        root.addWidget(self._build_ris_box())
        root.addWidget(self._build_excel_box())
        root.addWidget(self._build_log_box(), stretch=1)

    # -- Stats --------------------------------------------------------

    def _build_stats_box(self) -> QGroupBox:
        box = QGroupBox("Project Summary")
        grid = QGridLayout(box)
        grid.setSpacing(8)

        def _stat(row: int, col_offset: int, label: str) -> QLabel:
            grid.addWidget(QLabel(f"<b>{label}</b>"), row, col_offset)
            val = QLabel("—")
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val.setMinimumWidth(60)
            grid.addWidget(val, row, col_offset + 1)
            return val

        self._lbl_total    = _stat(0, 0, "Total records:")
        self._lbl_include  = _stat(0, 2, "Include:")
        self._lbl_exclude  = _stat(0, 4, "Exclude:")
        self._lbl_maybe    = _stat(1, 0, "Maybe:")
        self._lbl_undecided = _stat(1, 2, "Undecided:")

        grid.addWidget(QLabel("<b>Last export:</b>"), 1, 4)
        self._lbl_last_export = QLabel("—")
        self._lbl_last_export.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        grid.addWidget(self._lbl_last_export, 1, 5)

        # Column stretches so labels don't crowd
        for col in (1, 3, 5):
            grid.setColumnStretch(col, 1)

        return box

    # -- RIS ----------------------------------------------------------

    def _build_ris_box(self) -> QGroupBox:
        box = QGroupBox("RIS Export")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter range:"))
        self._ris_filter = QComboBox()
        self._ris_filter.addItems([
            "All",
            "Include only",
            "Exclude only",
            "Maybe only",
        ])
        filter_row.addWidget(self._ris_filter)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Options row
        opts_row = QHBoxLayout()
        self._ris_include_history = QCheckBox("Include screening history")
        self._ris_include_history.setChecked(True)
        opts_row.addWidget(self._ris_include_history)
        opts_row.addStretch()
        layout.addLayout(opts_row)

        # Button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_export_ris = QPushButton("Export RIS…")
        self._btn_export_ris.setFixedWidth(140)
        self._btn_export_ris.clicked.connect(self._on_export_ris)
        btn_row.addWidget(self._btn_export_ris)
        layout.addLayout(btn_row)

        return box

    # -- Excel --------------------------------------------------------

    def _build_excel_box(self) -> QGroupBox:
        box = QGroupBox("Excel Export")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        opts_row = QHBoxLayout()
        self._excel_include_extraction = QCheckBox("Include extracted data")
        self._excel_include_extraction.setChecked(True)
        opts_row.addWidget(self._excel_include_extraction)
        opts_row.addStretch()
        layout.addLayout(opts_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_export_excel = QPushButton("Export Excel…")
        self._btn_export_excel.setFixedWidth(140)
        self._btn_export_excel.clicked.connect(self._on_export_excel)
        btn_row.addWidget(self._btn_export_excel)
        layout.addLayout(btn_row)

        return box

    # -- Log ----------------------------------------------------------

    def _build_log_box(self) -> QGroupBox:
        box = QGroupBox("Export Log")
        layout = QVBoxLayout(box)
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setPlaceholderText("Export history will appear here…")
        self._log_view.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(self._log_view)
        return box

    # ------------------------------------------------------------------
    # Export actions
    # ------------------------------------------------------------------

    def _on_export_ris(self) -> None:
        if self._project is None:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save RIS file",
            "",
            "RIS files (*.ris);;All files (*)",
        )
        if not out_path:
            return

        filter_mode   = self._ris_filter.currentText()
        inc_history   = self._ris_include_history.isChecked()
        records       = self._filtered_records(filter_mode)
        decisions     = self._decisions
        history       = self._decision_history if inc_history else {}

        kwargs = dict(
            records=records,
            decisions=decisions,
            decision_history=history,
            out_path=out_path,
        )
        self._start_export("ris", kwargs, out_path)

    def _on_export_excel(self) -> None:
        if self._project is None:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Excel file",
            "",
            "Excel files (*.xlsx);;All files (*)",
        )
        if not out_path:
            return

        inc_extraction  = self._excel_include_extraction.isChecked()
        extracted       = self._extracted_values if inc_extraction else {}

        kwargs = dict(
            records=self._records,
            decisions=self._decisions,
            decision_history=self._decision_history,
            extracted_values=extracted,
            out_path=out_path,
        )
        self._start_export("excel", kwargs, out_path)

    # ------------------------------------------------------------------
    # Thread management
    # ------------------------------------------------------------------

    def _start_export(self, kind: str, kwargs: dict, out_path: str) -> None:
        """Launch the export worker in a background thread."""
        # Disable buttons while exporting
        self._set_buttons_enabled(False)

        self._thread = QThread(self)
        self._worker = _ExportWorker(kind, kwargs)
        self._worker.moveToThread(self._thread)

        # Wire signals
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_export_finished)
        self._worker.error.connect(self._on_export_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(lambda: self._set_buttons_enabled(True))

        self._thread.start()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._btn_export_ris.setEnabled(enabled)
        self._btn_export_excel.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Worker callbacks
    # ------------------------------------------------------------------

    def _on_export_finished(self, file_path: str, record_count: int) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._last_export_time = now
        self._refresh_stats()
        self._log(f"[{now}]  {file_path}  ({record_count} records)")

        QMessageBox.information(
            self,
            "Export Complete",
            f"Export successful!\n\nFile: {file_path}\nRecords: {record_count}",
        )

    def _on_export_error(self, message: str) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._log(f"[{now}]  ERROR: {message}")
        QMessageBox.critical(self, "Export Failed", f"Export error:\n\n{message}")

    # ------------------------------------------------------------------
    # Log helper
    # ------------------------------------------------------------------

    def _log(self, text: str) -> None:
        self._log_view.append(text)
