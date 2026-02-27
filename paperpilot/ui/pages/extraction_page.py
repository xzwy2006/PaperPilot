"""
ui/pages/extraction_page.py — AI Data Extraction page for PaperPilot.

Layout:
  Top toolbar: Provider combo | Model input | Extract buttons | Progress bar
  Left panel:  Record list with extraction status
  Right panel: Extracted fields table + per-field actions + Export to DB
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QProgressBar, QSplitter,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QFrame, QMessageBox, QInputDialog,
    QAbstractItemView, QSizePolicy,
)


# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------

_CONFIG_DIR  = Path.home() / ".paperpilot"
_PROVIDERS_FILE = _CONFIG_DIR / "ai_providers.json"


def _load_providers() -> dict:
    """Load ~/.paperpilot/ai_providers.json; return {} on error."""
    try:
        if _PROVIDERS_FILE.exists():
            with _PROVIDERS_FILE.open("r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return {}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Status colours for record list
# ---------------------------------------------------------------------------

COLOR_EXTRACTED = QColor("#c3e6cb")   # green
COLOR_FAILED    = QColor("#f5c6cb")   # red
COLOR_PENDING   = QColor("#e2e3e5")   # grey

STATUS_LABELS = {
    "extracted": "✅",
    "failed":    "❌",
    "pending":   "⬜",
}


# ---------------------------------------------------------------------------
# Worker: run AI extraction in background thread
# ---------------------------------------------------------------------------

class _ExtractionWorker(QObject):
    progress   = Signal(int, int)          # current, total
    result     = Signal(str, list)         # record_id, list[dict]
    error      = Signal(str, str)          # record_id, error_message
    finished   = Signal()

    def __init__(self, records: list[dict], provider_name: str, model: str,
                 project):
        super().__init__()
        self._records  = records
        self._provider_name = provider_name
        self._model    = model
        self._project  = project
        self._abort    = False

    def abort(self):
        self._abort = True

    def run(self):
        from paperpilot.core.ai.provider_config import ProviderConfig
        pc = ProviderConfig()
        provider = pc.get_provider(self._provider_name)

        if provider is None:
            for rec in self._records:
                self.error.emit(rec["id"], f"Provider '{self._provider_name}' not configured.")
            self.finished.emit()
            return

        total = len(self._records)
        for idx, rec in enumerate(self._records):
            if self._abort:
                break
            self.progress.emit(idx, total)
            try:
                fields = self._extract_record(provider, rec)
                self.result.emit(rec["id"], fields)
            except Exception as exc:
                self.error.emit(rec["id"], str(exc))

        self.progress.emit(total, total)
        self.finished.emit()

    def _extract_record(self, provider, rec: dict) -> list[dict]:
        """
        Call the AI provider to extract structured fields from a record's abstract.
        Returns a list of dicts: {field_key, value, confidence, evidence}.
        """
        title    = rec.get("title") or ""
        abstract = rec.get("abstract") or ""

        prompt = (
            "You are a systematic review data extraction assistant.\n"
            "Given the paper below, extract key data fields as JSON.\n"
            "Return a JSON array where each item has:\n"
            "  field_key (string), value (string), confidence (0-1 float), "
            "evidence (short quote from abstract).\n\n"
            f"Title: {title}\n"
            f"Abstract: {abstract}\n\n"
            "Extract fields: study_design, population, intervention, "
            "comparison, outcome, sample_size, follow_up_duration, "
            "country, funding_source.\n"
            "Respond with ONLY a JSON array."
        )

        # Use the provider's chat interface
        if hasattr(provider, "chat"):
            raw = provider.chat([{"role": "user", "content": prompt}],
                                model=self._model or None)
        elif hasattr(provider, "complete"):
            raw = provider.complete(prompt, model=self._model or None)
        else:
            raise RuntimeError("Provider has no chat/complete method.")

        # Parse JSON
        text = raw.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(l for l in lines if not l.startswith("```"))

        fields = json.loads(text)
        if not isinstance(fields, list):
            raise ValueError("Expected JSON array from AI.")
        return fields


# ---------------------------------------------------------------------------
# ExtractionPage
# ---------------------------------------------------------------------------

class ExtractionPage(QWidget):
    """AI data extraction page: provider config, record list, result review."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project  = None
        self._records:  list[dict] = []
        self._statuses: dict[str, str] = {}   # record_id → "pending"|"extracted"|"failed"
        self._results:  dict[str, list[dict]] = {}  # record_id → fields list
        self._current_record_id: Optional[str] = None
        self._worker:   Optional[_ExtractionWorker] = None
        self._thread:   Optional[QThread] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        self._project = project
        self._load_data()
        self._refresh_list()
        self._refresh_providers()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Top toolbar ───────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("Provider:"))
        self._provider_combo = QComboBox()
        self._provider_combo.setMinimumWidth(140)
        self._provider_combo.setToolTip("AI provider (from ai_providers.json)")
        toolbar.addWidget(self._provider_combo)

        toolbar.addWidget(QLabel("Model:"))
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText("(use provider default)")
        self._model_edit.setMaximumWidth(200)
        toolbar.addWidget(self._model_edit)

        self._extract_sel_btn = QPushButton("⚡ Extract Selected")
        self._extract_sel_btn.setStyleSheet(
            "padding:5px 12px; background:#0d6efd; color:#fff;"
            "border-radius:4px; border:none;"
        )
        self._extract_sel_btn.clicked.connect(self._on_extract_selected)
        self._extract_sel_btn.setEnabled(False)
        toolbar.addWidget(self._extract_sel_btn)

        self._extract_all_btn = QPushButton("🚀 Extract All (include)")
        self._extract_all_btn.setStyleSheet(
            "padding:5px 12px; background:#198754; color:#fff;"
            "border-radius:4px; border:none;"
        )
        self._extract_all_btn.clicked.connect(self._on_extract_all)
        self._extract_all_btn.setEnabled(False)
        toolbar.addWidget(self._extract_all_btn)

        self._abort_btn = QPushButton("⏹ Stop")
        self._abort_btn.setStyleSheet(
            "padding:5px 12px; background:#dc3545; color:#fff;"
            "border-radius:4px; border:none;"
        )
        self._abort_btn.clicked.connect(self._on_abort)
        self._abort_btn.setEnabled(False)
        toolbar.addWidget(self._abort_btn)

        toolbar.addStretch()
        root.addLayout(toolbar)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFixedHeight(14)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#ccc;")
        root.addWidget(sep)

        # ── Main splitter ─────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # -- Left: record list ----------------------------------------
        left_box = QGroupBox("Records")
        left_layout = QVBoxLayout(left_box)
        left_layout.setSpacing(4)

        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(False)
        self._list_widget.setSpacing(1)
        self._list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list_widget.currentItemChanged.connect(self._on_record_selected)
        left_layout.addWidget(self._list_widget, 1)

        self._list_stats_lbl = QLabel("")
        self._list_stats_lbl.setStyleSheet("font-size:11px; color:#555;")
        left_layout.addWidget(self._list_stats_lbl)

        splitter.addWidget(left_box)

        # -- Right: results panel -------------------------------------
        right_box = QGroupBox("Extraction Results")
        right_layout = QVBoxLayout(right_box)
        right_layout.setSpacing(6)

        # Record title display
        self._rec_title_lbl = QLabel("← Select a record")
        self._rec_title_lbl.setWordWrap(True)
        self._rec_title_lbl.setStyleSheet(
            "font-size:14px; font-weight:bold; color:#1a1a2e; padding:2px 0;"
        )
        right_layout.addWidget(self._rec_title_lbl)

        # Fields table
        self._fields_table = QTableWidget(0, 4)
        self._fields_table.setHorizontalHeaderLabels(
            ["Field", "Value", "Confidence", "Evidence"]
        )
        self._fields_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._fields_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._fields_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._fields_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._fields_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._fields_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._fields_table.setAlternatingRowColors(True)
        self._fields_table.verticalHeader().setVisible(False)
        self._fields_table.setMinimumHeight(200)
        right_layout.addWidget(self._fields_table, 1)

        # Per-field action buttons
        field_btn_row = QHBoxLayout()

        self._accept_btn = QPushButton("✅ Accept")
        self._accept_btn.setStyleSheet(
            "padding:5px 14px; background:#28a745; color:#fff;"
            "border-radius:4px; border:none;"
        )
        self._accept_btn.clicked.connect(self._on_accept_field)
        self._accept_btn.setEnabled(False)

        self._edit_btn = QPushButton("✏️ Edit")
        self._edit_btn.setStyleSheet(
            "padding:5px 14px; background:#ffc107; color:#212529;"
            "border-radius:4px; border:none;"
        )
        self._edit_btn.clicked.connect(self._on_edit_field)
        self._edit_btn.setEnabled(False)

        self._reject_btn = QPushButton("❌ Reject")
        self._reject_btn.setStyleSheet(
            "padding:5px 14px; background:#dc3545; color:#fff;"
            "border-radius:4px; border:none;"
        )
        self._reject_btn.clicked.connect(self._on_reject_field)
        self._reject_btn.setEnabled(False)

        field_btn_row.addWidget(self._accept_btn)
        field_btn_row.addWidget(self._edit_btn)
        field_btn_row.addWidget(self._reject_btn)
        field_btn_row.addStretch()
        right_layout.addLayout(field_btn_row)

        # Connect field selection to enable buttons
        self._fields_table.itemSelectionChanged.connect(self._on_field_selection_changed)

        # Export button
        export_row = QHBoxLayout()
        export_row.addStretch()
        self._export_btn = QPushButton("💾 Export to DB")
        self._export_btn.setStyleSheet(
            "padding:6px 18px; background:#6610f2; color:#fff;"
            "border-radius:5px; border:none; font-size:13px;"
        )
        self._export_btn.clicked.connect(self._on_export_to_db)
        self._export_btn.setEnabled(False)
        export_row.addWidget(self._export_btn)
        right_layout.addLayout(export_row)

        splitter.addWidget(right_box)
        splitter.setSizes([320, 680])

        root.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self) -> None:
        if not self._project:
            return
        conn = self._project.conn

        # All included records (or all if no screening table)
        try:
            rows = conn.execute(
                """
                SELECT r.id, r.title, r.abstract, r.year
                FROM records r
                INNER JOIN screening_decisions sd ON sd.record_id = r.id
                WHERE sd.decision = 'include'
                  AND sd.ts = (
                      SELECT MAX(sd2.ts) FROM screening_decisions sd2
                      WHERE sd2.record_id = r.id AND sd2.stage = sd.stage
                  )
                ORDER BY r.year DESC, r.title
                """
            ).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT id, title, abstract, year FROM records ORDER BY year DESC, title"
            ).fetchall()

        self._records = [dict(r) for r in rows]

        # Pre-load existing extracted_values to determine statuses
        self._statuses.clear()
        self._results.clear()
        for rec in self._records:
            rid = rec["id"]
            evs = conn.execute(
                "SELECT * FROM extracted_values WHERE record_id = ?", (rid,)
            ).fetchall()
            if evs:
                self._results[rid] = [dict(e) for e in evs]
                self._statuses[rid] = "extracted"
            else:
                self._statuses[rid] = "pending"

    def _refresh_providers(self) -> None:
        self._provider_combo.clear()
        providers = _load_providers()
        if providers:
            for name in providers:
                self._provider_combo.addItem(name)
        else:
            self._provider_combo.addItem("(no providers configured)")

    # ------------------------------------------------------------------
    # List refresh
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        self._list_widget.clear()
        total      = len(self._records)
        n_extracted = sum(1 for s in self._statuses.values() if s == "extracted")
        n_failed    = sum(1 for s in self._statuses.values() if s == "failed")
        n_pending   = total - n_extracted - n_failed

        self._list_stats_lbl.setText(
            f"Total: {total}  ✅ {n_extracted}  ❌ {n_failed}  ⬜ {n_pending}"
        )
        self._extract_sel_btn.setEnabled(self._project is not None)
        self._extract_all_btn.setEnabled(self._project is not None)

        for rec in self._records:
            rid    = rec["id"]
            status = self._statuses.get(rid, "pending")
            icon   = STATUS_LABELS.get(status, "⬜")
            title  = rec.get("title") or rid
            item   = QListWidgetItem(f"{icon}  {title}")
            item.setData(Qt.UserRole, rid)

            if status == "extracted":
                item.setBackground(QBrush(COLOR_EXTRACTED))
            elif status == "failed":
                item.setBackground(QBrush(COLOR_FAILED))
            else:
                item.setBackground(QBrush(COLOR_PENDING))

            self._list_widget.addItem(item)

    # ------------------------------------------------------------------
    # Record selection
    # ------------------------------------------------------------------

    def _on_record_selected(self, current: QListWidgetItem, _prev) -> None:
        if current is None:
            return
        rid = current.data(Qt.UserRole)
        self._current_record_id = rid
        rec = next((r for r in self._records if r["id"] == rid), None)
        if rec:
            self._rec_title_lbl.setText(rec.get("title") or rid)
        self._populate_fields(rid)

    def _populate_fields(self, record_id: str) -> None:
        self._fields_table.setRowCount(0)
        fields = self._results.get(record_id, [])
        has_results = bool(fields)

        for row_idx, field in enumerate(fields):
            self._fields_table.insertRow(row_idx)

            fkey  = field.get("field_key") or field.get("field") or "—"
            value = field.get("value") or "—"
            conf  = field.get("confidence")
            evid  = field.get("evidence") or field.get("source_quote") or "—"

            conf_str = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"

            key_item  = QTableWidgetItem(fkey)
            val_item  = QTableWidgetItem(value)
            conf_item = QTableWidgetItem(conf_str)
            conf_item.setTextAlignment(Qt.AlignCenter)
            evid_item = QTableWidgetItem(evid)

            # Store field index for later retrieval
            key_item.setData(Qt.UserRole, row_idx)

            # Highlight low-confidence rows in red
            if isinstance(conf, (int, float)) and conf < 0.6:
                red_bg = QBrush(QColor("#f5c6cb"))
                for item in (key_item, val_item, conf_item, evid_item):
                    item.setBackground(red_bg)

            # Mark status visually
            status = field.get("status", "pending")
            if status == "accepted":
                green_fg = QBrush(QColor("#155724"))
                for item in (key_item, val_item):
                    item.setForeground(green_fg)
            elif status == "rejected":
                grey_fg = QBrush(QColor("#aaa"))
                for item in (key_item, val_item, conf_item, evid_item):
                    item.setForeground(grey_fg)

            self._fields_table.setItem(row_idx, 0, key_item)
            self._fields_table.setItem(row_idx, 1, val_item)
            self._fields_table.setItem(row_idx, 2, conf_item)
            self._fields_table.setItem(row_idx, 3, evid_item)

        self._fields_table.resizeRowsToContents()
        self._export_btn.setEnabled(has_results and self._project is not None)

    # ------------------------------------------------------------------
    # Field selection → enable buttons
    # ------------------------------------------------------------------

    def _on_field_selection_changed(self) -> None:
        has_sel = bool(self._fields_table.selectedItems())
        self._accept_btn.setEnabled(has_sel)
        self._edit_btn.setEnabled(has_sel)
        self._reject_btn.setEnabled(has_sel)

    def _selected_field_row(self) -> int:
        rows = self._fields_table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    # ------------------------------------------------------------------
    # Per-field actions
    # ------------------------------------------------------------------

    def _on_accept_field(self) -> None:
        row = self._selected_field_row()
        if row < 0 or not self._current_record_id:
            return
        self._set_field_status(row, "accepted")

    def _on_reject_field(self) -> None:
        row = self._selected_field_row()
        if row < 0 or not self._current_record_id:
            return
        self._set_field_status(row, "rejected")

    def _on_edit_field(self) -> None:
        row = self._selected_field_row()
        if row < 0 or not self._current_record_id:
            return
        val_item = self._fields_table.item(row, 1)
        if val_item is None:
            return
        current_val = val_item.text()
        new_val, ok = QInputDialog.getText(
            self, "Edit Value", "New value:", text=current_val
        )
        if ok and new_val.strip():
            val_item.setText(new_val.strip())
            # Update in-memory results
            rid = self._current_record_id
            if rid in self._results and row < len(self._results[rid]):
                self._results[rid][row]["value"] = new_val.strip()
                self._results[rid][row]["status"] = "accepted"
            self._set_field_status(row, "accepted")

    def _set_field_status(self, row: int, status: str) -> None:
        rid = self._current_record_id
        if not rid or rid not in self._results:
            return
        if row >= len(self._results[rid]):
            return
        self._results[rid][row]["status"] = status

        # Update row colours
        if status == "accepted":
            fg = QBrush(QColor("#155724"))
        elif status == "rejected":
            fg = QBrush(QColor("#aaa"))
        else:
            fg = QBrush(QColor("#000"))

        for col in range(self._fields_table.columnCount()):
            item = self._fields_table.item(row, col)
            if item:
                item.setForeground(fg)

    # ------------------------------------------------------------------
    # Extraction: selected records
    # ------------------------------------------------------------------

    def _on_extract_selected(self) -> None:
        selected_rids = set()
        for item in self._list_widget.selectedItems():
            selected_rids.add(item.data(Qt.UserRole))
        if not selected_rids:
            QMessageBox.information(self, "No Selection", "Please select at least one record.")
            return
        records = [r for r in self._records if r["id"] in selected_rids]
        self._start_extraction(records)

    # ------------------------------------------------------------------
    # Extraction: all included records
    # ------------------------------------------------------------------

    def _on_extract_all(self) -> None:
        records = list(self._records)
        if not records:
            QMessageBox.information(self, "No Records", "No records available.")
            return
        self._start_extraction(records)

    # ------------------------------------------------------------------
    # Start extraction worker
    # ------------------------------------------------------------------

    def _start_extraction(self, records: list[dict]) -> None:
        provider_name = self._provider_combo.currentText()
        model         = self._model_edit.text().strip()

        if not provider_name or provider_name.startswith("("):
            QMessageBox.warning(
                self, "No Provider",
                "Please configure an AI provider in Settings first."
            )
            return

        # Disable buttons, show progress
        self._extract_sel_btn.setEnabled(False)
        self._extract_all_btn.setEnabled(False)
        self._abort_btn.setEnabled(True)
        self._progress.setRange(0, len(records))
        self._progress.setValue(0)
        self._progress.setVisible(True)

        # Spawn worker thread
        self._thread = QThread()
        self._worker = _ExtractionWorker(records, provider_name, model, self._project)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.result.connect(self._on_worker_result)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._thread.quit)

        self._thread.start()

    # ------------------------------------------------------------------
    # Worker signals
    # ------------------------------------------------------------------

    def _on_worker_progress(self, current: int, total: int) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        self._progress.setFormat(f"{current}/{total}")

    def _on_worker_result(self, record_id: str, fields: list[dict]) -> None:
        # Normalise field dicts
        normalised = []
        for f in fields:
            normalised.append({
                "field_key":    f.get("field_key") or f.get("field") or "unknown",
                "value":        f.get("value") or "",
                "confidence":   f.get("confidence"),
                "evidence":     f.get("evidence") or "",
                "status":       "pending",
            })
        self._results[record_id]  = normalised
        self._statuses[record_id] = "extracted"
        self._refresh_list()
        # Refresh right panel if this is the currently-selected record
        if self._current_record_id == record_id:
            self._populate_fields(record_id)

    def _on_worker_error(self, record_id: str, error_msg: str) -> None:
        self._statuses[record_id] = "failed"
        self._results[record_id]  = [{"field_key": "error", "value": error_msg,
                                       "confidence": None, "evidence": "", "status": "failed"}]
        self._refresh_list()

    def _on_worker_finished(self) -> None:
        self._abort_btn.setEnabled(False)
        self._extract_sel_btn.setEnabled(True)
        self._extract_all_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._worker = None

    # ------------------------------------------------------------------
    # Abort
    # ------------------------------------------------------------------

    def _on_abort(self) -> None:
        if self._worker:
            self._worker.abort()
        self._abort_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Export to DB
    # ------------------------------------------------------------------

    def _on_export_to_db(self) -> None:
        rid = self._current_record_id
        if not rid or not self._project:
            return
        fields = self._results.get(rid, [])
        if not fields:
            QMessageBox.information(self, "Nothing to Export", "No extraction results to save.")
            return

        conn = self._project.conn
        now  = _now_iso()
        saved = 0

        for field in fields:
            if field.get("status") == "rejected":
                continue
            ev_id = str(uuid.uuid4())
            conn.execute(
                """INSERT OR REPLACE INTO extracted_values
                   (id, record_id, field_key, value, confidence, source_quote,
                    source, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    ev_id,
                    rid,
                    field.get("field_key") or "unknown",
                    field.get("value") or "",
                    field.get("confidence"),
                    field.get("evidence") or "",
                    "ai",
                    field.get("status") or "pending",
                    now,
                    now,
                ),
            )
            saved += 1

        conn.commit()
        self._statuses[rid] = "extracted"
        self._refresh_list()
        QMessageBox.information(
            self, "Exported",
            f"Saved {saved} field(s) to the database for this record."
        )
