"""
ui/pages/standardize_page.py — Data standardization review page for PaperPilot.

Layout:
  Top    : Provider / Model selector + "Standardize All" button
  Middle : left = field list (QListWidget)  |  right = results table
  Bottom : AI audit results panel
"""
from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QColor, QBrush, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QFormLayout, QLabel, QComboBox,
    QListWidget, QListWidgetItem, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit,
    QHeaderView, QMessageBox, QProgressDialog,
    QSizePolicy,
)

# ---------------------------------------------------------------------------
# Colour constants
# ---------------------------------------------------------------------------
COLOR_OK      = QColor("#c3e6cb")   # green  — standardized
COLOR_PENDING = QColor("#e2e3e5")   # grey   — not yet standardized
COLOR_PROBLEM = QColor("#f5c6cb")   # red    — has issues
COLOR_LOW_CONF = QColor("#f8d7da")  # light red — low confidence rows
CONF_THRESHOLD = 0.70               # below this → highlight red


# ---------------------------------------------------------------------------
# Background worker: call AI standardize for all records
# ---------------------------------------------------------------------------

class _StandardizeWorker(QObject):
    progress    = Signal(int, int, str)   # current, total, msg
    record_done = Signal(str, list)       # field_key, list of result dicts
    finished    = Signal()
    error       = Signal(str)

    def __init__(self, project, field_keys: list[str], provider, model: str):
        super().__init__()
        self._project   = project
        self._field_keys = field_keys
        self._provider  = provider
        self._model     = model

    def run(self):
        try:
            from paperpilot.core.extraction import standardize_field  # type: ignore
        except ImportError:
            standardize_field = None

        total = len(self._field_keys)
        for idx, field_key in enumerate(self._field_keys):
            self.progress.emit(idx, total, f"Standardizing: {field_key}")
            try:
                if standardize_field is not None:
                    results = standardize_field(
                        self._project, field_key,
                        provider=self._provider, model=self._model,
                    )
                else:
                    # Stub: return empty list
                    results = []
                self.record_done.emit(field_key, results)
            except Exception as exc:
                self.record_done.emit(field_key, [{"error": str(exc)}])

        self.finished.emit()


# ---------------------------------------------------------------------------
# StandardizePage — main widget
# ---------------------------------------------------------------------------

class StandardizePage(QWidget):
    """Data standardization review and control page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project  = None
        self._fields: list[str] = []
        self._field_status: dict[str, str] = {}   # field_key → 'ok'|'pending'|'problem'
        self._results_cache: dict[str, list[dict]] = {}
        self._worker: Optional[_StandardizeWorker] = None
        self._thread: Optional[QThread]            = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        """Called by the main window when a project is opened."""
        self._project = project
        self._load_fields()
        self._refresh_field_list()
        self._refresh_table("")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Top bar: provider / model / run button ─────────────────────
        top_box = QGroupBox("Standardization Settings")
        top_layout = QHBoxLayout(top_box)
        top_layout.setSpacing(12)

        top_layout.addWidget(QLabel("Provider:"))
        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["openai", "anthropic", "ollama", "custom"])
        self._provider_combo.setMinimumWidth(130)
        top_layout.addWidget(self._provider_combo)

        top_layout.addWidget(QLabel("Model:"))
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.addItems([
            "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo",
            "claude-3-5-sonnet-20241022", "claude-3-haiku-20240307",
        ])
        self._model_combo.setMinimumWidth(220)
        top_layout.addWidget(self._model_combo)

        top_layout.addStretch()

        self._std_all_btn = QPushButton("⚡  Standardize All")
        self._std_all_btn.setMinimumHeight(34)
        self._std_all_btn.setStyleSheet(
            "QPushButton { background-color: #1a73e8; color: white; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1557b0; }"
            "QPushButton:disabled { background-color: #aaa; }"
        )
        self._std_all_btn.clicked.connect(self._run_standardize_all)
        top_layout.addWidget(self._std_all_btn)

        root.addWidget(top_box)

        # ── Middle splitter: field list | results table ─────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Left: field list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Fields")
        lbl.setStyleSheet("font-weight: bold;")
        left_layout.addWidget(lbl)

        self._field_list = QListWidget()
        self._field_list.setFixedWidth(200)
        self._field_list.currentTextChanged.connect(self._on_field_selected)
        left_layout.addWidget(self._field_list)

        legend_layout = QVBoxLayout()
        for color, desc in [
            (COLOR_OK,      "✓ Standardized"),
            (COLOR_PENDING, "○ Not standardized"),
            (COLOR_PROBLEM, "✗ Has issues"),
        ]:
            legend_row = QHBoxLayout()
            dot = QLabel("█")
            dot.setStyleSheet(f"color: {color.name()};")
            legend_row.addWidget(dot)
            legend_row.addWidget(QLabel(desc))
            legend_row.addStretch()
            legend_layout.addLayout(legend_row)
        left_layout.addLayout(legend_layout)

        splitter.addWidget(left_panel)

        # Right: results table
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_layout.addWidget(QLabel("Standardization Results"))

        self._results_table = QTableWidget(0, 5)
        self._results_table.setHorizontalHeaderLabels(
            ["Record", "Original", "Normalized", "Unit", "Confidence"]
        )
        self._results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._results_table.setAlternatingRowColors(True)
        self._results_table.setSelectionBehavior(QTableWidget.SelectRows)
        right_layout.addWidget(self._results_table)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, stretch=1)

        # ── Bottom: AI audit results ────────────────────────────────────
        audit_box = QGroupBox("AI Audit Results")
        audit_layout = QVBoxLayout(audit_box)

        audit_header = QHBoxLayout()
        self._overall_conf_lbl = QLabel("Overall confidence: —")
        font = QFont()
        font.setBold(True)
        self._overall_conf_lbl.setFont(font)
        audit_header.addWidget(self._overall_conf_lbl)
        audit_header.addStretch()
        audit_layout.addLayout(audit_header)

        self._flags_edit = QTextEdit()
        self._flags_edit.setReadOnly(True)
        self._flags_edit.setMaximumHeight(110)
        self._flags_edit.setPlaceholderText(
            "AI audit flags will appear here after standardization…"
        )
        self._flags_edit.setStyleSheet(
            "QTextEdit { font-size: 12px; background: #fafafa; }"
        )
        audit_layout.addWidget(self._flags_edit)

        root.addWidget(audit_box)

    # ------------------------------------------------------------------
    # Data loading helpers
    # ------------------------------------------------------------------

    def _load_fields(self):
        """Load field keys from the extraction template in the DB."""
        self._fields = []
        self._field_status = {}
        if self._project is None:
            return
        try:
            cur = self._project.conn.execute(
                "SELECT schema_json FROM extraction_templates LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                schema = json.loads(row[0])
                if isinstance(schema, list):
                    self._fields = [f.get("key", "") for f in schema if f.get("key")]
                elif isinstance(schema, dict):
                    self._fields = list(schema.keys())
        except Exception:
            pass

        if not self._fields:
            # Fallback: read distinct field_key from extracted_values
            try:
                cur = self._project.conn.execute(
                    "SELECT DISTINCT field_key FROM extracted_values ORDER BY field_key"
                )
                self._fields = [r[0] for r in cur.fetchall()]
            except Exception:
                pass

        # Compute per-field status
        for fk in self._fields:
            self._field_status[fk] = self._compute_field_status(fk)

    def _compute_field_status(self, field_key: str) -> str:
        """Return 'ok', 'pending', or 'problem' for a given field key."""
        if self._project is None:
            return "pending"
        try:
            cur = self._project.conn.execute(
                "SELECT is_standardized, confidence, status FROM extracted_values "
                "WHERE field_key = ?",
                (field_key,),
            )
            rows = cur.fetchall()
        except Exception:
            return "pending"
        if not rows:
            return "pending"
        has_not_std = any(r[0] == 0 for r in rows)
        has_rejected = any(r[2] == "rejected" for r in rows)
        has_low_conf = any(
            r[1] is not None and r[1] < CONF_THRESHOLD for r in rows
        )
        if has_rejected or has_low_conf:
            return "problem"
        if has_not_std:
            return "pending"
        return "ok"

    def _refresh_field_list(self):
        self._field_list.clear()
        for fk in self._fields:
            item = QListWidgetItem(fk)
            status = self._field_status.get(fk, "pending")
            if status == "ok":
                item.setBackground(QBrush(COLOR_OK))
            elif status == "problem":
                item.setBackground(QBrush(COLOR_PROBLEM))
            else:
                item.setBackground(QBrush(COLOR_PENDING))
            self._field_list.addItem(item)

    def _refresh_table(self, field_key: str):
        """Populate the results table for the given field key."""
        self._results_table.setRowCount(0)
        self._flags_edit.clear()
        self._overall_conf_lbl.setText("Overall confidence: —")

        if not field_key or self._project is None:
            return

        # If we have cached AI results, show them
        if field_key in self._results_cache:
            self._populate_table_from_cache(field_key)
            return

        # Otherwise load from DB
        try:
            cur = self._project.conn.execute(
                "SELECT record_id, value, value_standardized, confidence, status "
                "FROM extracted_values WHERE field_key = ? ORDER BY record_id",
                (field_key,),
            )
            rows = cur.fetchall()
        except Exception as exc:
            self._flags_edit.setText(f"DB error: {exc}")
            return

        self._results_table.setRowCount(len(rows))
        for row_idx, (rec_id, val, val_std, conf, status) in enumerate(rows):
            conf_str = f"{conf:.2f}" if isinstance(conf, float) else str(conf or "—")
            cells = [
                str(rec_id or ""),
                str(val     or ""),
                str(val_std or ""),
                "",                 # unit not in DB yet — reserved
                conf_str,
            ]
            is_low = isinstance(conf, float) and conf < CONF_THRESHOLD
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if is_low:
                    item.setBackground(QBrush(COLOR_LOW_CONF))
                self._results_table.setItem(row_idx, col, item)

    def _populate_table_from_cache(self, field_key: str):
        results = self._results_cache.get(field_key, [])
        self._results_table.setRowCount(len(results))
        flags_lines: list[str] = []
        conf_vals: list[float] = []

        for row_idx, r in enumerate(results):
            if "error" in r:
                cells = [r.get("record_id", "?"), "", "", "", "ERROR"]
                is_low = True
            else:
                conf = r.get("confidence")
                conf_str = f"{conf:.2f}" if isinstance(conf, float) else str(conf or "—")
                if isinstance(conf, float):
                    conf_vals.append(conf)
                is_low = isinstance(conf, float) and conf < CONF_THRESHOLD
                cells = [
                    str(r.get("record_id", "")),
                    str(r.get("original",   "")),
                    str(r.get("normalized", "")),
                    str(r.get("unit",       "")),
                    conf_str,
                ]
                if r.get("flags"):
                    flags_lines.extend(
                        [f"[{r.get('record_id', '?')}] {f}" for f in r["flags"]]
                    )

            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if is_low:
                    item.setBackground(QBrush(COLOR_LOW_CONF))
                self._results_table.setItem(row_idx, col, item)

        if conf_vals:
            avg_conf = sum(conf_vals) / len(conf_vals)
            self._overall_conf_lbl.setText(
                f"Overall confidence: {avg_conf:.2f}  (n={len(conf_vals)})"
            )
        self._flags_edit.setPlainText("\n".join(flags_lines) if flags_lines else "No flags.")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_field_selected(self, field_key: str):
        self._refresh_table(field_key)

    def _run_standardize_all(self):
        if not self._fields:
            QMessageBox.information(
                self, "No Fields",
                "No extraction fields found.\n"
                "Please run data extraction first.",
            )
            return
        if self._thread and self._thread.isRunning():
            return

        provider_name = self._provider_combo.currentText()
        model         = self._model_combo.currentText()

        # Resolve provider object (best-effort)
        provider = None
        try:
            from paperpilot.core.ai import get_provider  # type: ignore
            provider = get_provider(provider_name)
        except Exception:
            pass

        progress = QProgressDialog(
            "Standardizing fields…", "Cancel", 0, len(self._fields), self
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        self._results_cache.clear()
        self._std_all_btn.setEnabled(False)

        self._worker = _StandardizeWorker(
            self._project, self._fields, provider, model
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(
            lambda cur, total, msg: (
                progress.setValue(cur),
                progress.setLabelText(msg),
            )
        )
        self._worker.record_done.connect(self._on_field_done)
        self._worker.finished.connect(self._on_standardize_finished)
        self._worker.error.connect(self._on_standardize_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)

        def _cleanup():
            progress.close()
            self._std_all_btn.setEnabled(True)

        self._thread.finished.connect(_cleanup)
        self._thread.start()

    def _on_field_done(self, field_key: str, results: list):
        self._results_cache[field_key] = results
        # Recompute status
        has_error = any("error" in r for r in results)
        has_low   = any(
            isinstance(r.get("confidence"), float) and r["confidence"] < CONF_THRESHOLD
            for r in results
        )
        if has_error or has_low:
            self._field_status[field_key] = "problem"
        elif results:
            self._field_status[field_key] = "ok"
        else:
            self._field_status[field_key] = "pending"

        self._refresh_field_list()
        # If this field is currently selected, refresh the table
        current = self._field_list.currentItem()
        if current and current.text() == field_key:
            self._refresh_table(field_key)

    def _on_standardize_finished(self):
        self._refresh_field_list()
        self._flags_edit.setPlainText("Standardization complete.")

    def _on_standardize_error(self, msg: str):
        QMessageBox.critical(self, "Standardization Error", msg)
