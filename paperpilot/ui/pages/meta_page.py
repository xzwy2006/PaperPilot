"""
ui/pages/meta_page.py — Meta-analysis configuration and results page for PaperPilot.

Layout:
  Top    : Analysis Settings (QGroupBox)
  Middle : Results (QTabWidget: Summary | Forest Plot)
  Bottom : Log output (QTextEdit, read-only)
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QFormLayout, QLabel, QComboBox,
    QCheckBox, QLineEdit, QPushButton, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit,
    QHeaderView, QMessageBox, QFileDialog, QSizePolicy,
)

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
COLOR_SUBGROUP_HEADER = QColor("#dce8f8")   # light blue header rows
COLOR_LOW_CONF        = QColor("#f8d7da")   # light red for problem rows


# ---------------------------------------------------------------------------
# Background worker: run R script
# ---------------------------------------------------------------------------

class _MetaWorker(QObject):
    """Run a metafor R script in a background thread."""

    log_line   = Signal(str)
    finished   = Signal(dict)   # result dict or {}
    error      = Signal(str)

    def __init__(self, rscript_path: str, script: str):
        super().__init__()
        self._rscript = rscript_path
        self._script  = script

    def run(self):
        with tempfile.NamedTemporaryFile(
            suffix=".R", mode="w", encoding="utf-8", delete=False
        ) as tf:
            tf.write(self._script)
            tf_path = tf.name

        try:
            proc = subprocess.Popen(
                [self._rscript, tf_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            output_lines: list[str] = []
            for line in proc.stdout:
                line = line.rstrip("\n")
                output_lines.append(line)
                self.log_line.emit(line)

            proc.wait()
            # Parse JSON result block from R output
            result = {}
            json_buf: list[str] = []
            in_json = False
            for ln in output_lines:
                if ln.strip() == "###JSON_START###":
                    in_json = True
                    continue
                if ln.strip() == "###JSON_END###":
                    in_json = False
                    try:
                        result = json.loads("\n".join(json_buf))
                    except Exception as exc:
                        self.log_line.emit(f"[JSON parse error] {exc}")
                    break
                if in_json:
                    json_buf.append(ln)

            if proc.returncode != 0:
                self.error.emit(f"R exited with code {proc.returncode}")
            else:
                self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            try:
                os.unlink(tf_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# R-script builder
# ---------------------------------------------------------------------------

def _build_r_script(
    data_rows: list[dict],
    effect_field: str,
    se_field: str,
    method: str,
    subgroup_field: Optional[str],
) -> str:
    """Construct an R script that runs metafor and outputs JSON."""
    # Build inline data frame in R
    effects = []
    ses     = []
    labels  = []
    subgroups: list[str] = []

    for row in data_rows:
        eff = row.get(effect_field)
        se  = row.get(se_field)
        if eff is None or se is None:
            continue
        try:
            float(eff); float(se)
        except (TypeError, ValueError):
            continue
        effects.append(str(eff))
        ses.append(str(se))
        labels.append(str(row.get("record_id", "?")).replace("'", "\\'"))
        if subgroup_field:
            subgroups.append(str(row.get(subgroup_field, "NA")).replace("'", "\\'"))

    if not effects:
        return (
            "cat('###JSON_START###\n')\n"
            "cat('{\"error\": \"No numeric data rows found\"}\n')\n"
            "cat('###JSON_END###\n')\n"
        )

    eff_r  = "c(" + ", ".join(effects) + ")"
    se_r   = "c(" + ", ".join(ses) + ")"
    lbl_r  = "c('" + "', '".join(labels) + "')"

    subgroup_block = ""
    subgroup_analysis = ""
    if subgroup_field and subgroups:
        sg_r = "c('" + "', '".join(subgroups) + "')"
        subgroup_block = f"subgroup <- {sg_r}\n"
        subgroup_analysis = """
# Subgroup analysis
sg_results <- list()
for (sg in unique(subgroup)) {
  idx <- which(subgroup == sg)
  if (length(idx) < 2) next
  res_sg <- tryCatch(rma(yi=yi[idx], sei=sei[idx], method=method_str), error=function(e) NULL)
  if (!is.null(res_sg)) {
    sg_results[[sg]] <- list(
      estimate = round(as.numeric(res_sg$b), 6),
      ci_lb    = round(as.numeric(res_sg$ci.lb), 6),
      ci_ub    = round(as.numeric(res_sg$ci.ub), 6),
      I2       = round(as.numeric(res_sg$I2), 2),
      tau2     = round(as.numeric(res_sg$tau2), 6),
      k        = res_sg$k
    )
  }
}
"""
    else:
        subgroup_analysis = "sg_results <- list()"

    script = f"""
suppressMessages(library(metafor))

yi  <- {eff_r}
sei <- {se_r}
labels <- {lbl_r}
{subgroup_block}
method_str <- "{method}"

res <- rma(yi=yi, sei=sei, method=method_str)

{subgroup_analysis}

out <- list(
  estimate  = round(as.numeric(res$b), 6),
  ci_lb     = round(as.numeric(res$ci.lb), 6),
  ci_ub     = round(as.numeric(res$ci.ub), 6),
  I2        = round(as.numeric(res$I2), 2),
  tau2      = round(as.numeric(res$tau2), 6),
  Q         = round(as.numeric(res$QE), 4),
  Q_pval    = round(as.numeric(res$QEp), 6),
  k         = res$k,
  method    = method_str,
  subgroups = sg_results
)

cat("###JSON_START###\\n")
cat(toJSON(out, auto_unbox=TRUE), "\\n")
cat("###JSON_END###\\n")
"""
    return script


# ---------------------------------------------------------------------------
# Summary Tab
# ---------------------------------------------------------------------------

class _SummaryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ── Overall effect size (large display) ──────────────────────────
        effect_box = QGroupBox("Overall Effect")
        effect_layout = QVBoxLayout(effect_box)
        self._effect_lbl = QLabel("—")
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        self._effect_lbl.setFont(font)
        self._effect_lbl.setAlignment(Qt.AlignCenter)
        self._ci_lbl = QLabel("")
        self._ci_lbl.setAlignment(Qt.AlignCenter)
        effect_layout.addWidget(self._effect_lbl)
        effect_layout.addWidget(self._ci_lbl)
        layout.addWidget(effect_box)

        # ── Heterogeneity statistics ─────────────────────────────────────
        stats_box = QGroupBox("Heterogeneity Statistics")
        stats_layout = QVBoxLayout(stats_box)
        self._stats_table = QTableWidget(0, 2)
        self._stats_table.setHorizontalHeaderLabels(["Statistic", "Value"])
        self._stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._stats_table.verticalHeader().setVisible(False)
        self._stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._stats_table.setMaximumHeight(140)
        stats_layout.addWidget(self._stats_table)
        layout.addWidget(stats_box)

        # ── Subgroup results ─────────────────────────────────────────────
        self._subgroup_box = QGroupBox("Subgroup Results")
        sg_layout = QVBoxLayout(self._subgroup_box)
        self._sg_table = QTableWidget(0, 6)
        self._sg_table.setHorizontalHeaderLabels(
            ["Subgroup", "k", "Estimate", "CI Lower", "CI Upper", "I²"]
        )
        self._sg_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._sg_table.verticalHeader().setVisible(False)
        self._sg_table.setEditTriggers(QTableWidget.NoEditTriggers)
        sg_layout.addWidget(self._sg_table)
        self._subgroup_box.setVisible(False)
        layout.addWidget(self._subgroup_box)

        layout.addStretch()

    # ------------------------------------------------------------------
    def update_results(self, result: dict):
        """Populate summary from parsed R JSON result."""
        if "error" in result:
            self._effect_lbl.setText("Error")
            self._ci_lbl.setText(result["error"])
            return

        estimate = result.get("estimate", "N/A")
        ci_lb    = result.get("ci_lb", "N/A")
        ci_ub    = result.get("ci_ub", "N/A")
        self._effect_lbl.setText(
            f"{estimate:.4f}" if isinstance(estimate, float) else str(estimate)
        )
        if isinstance(ci_lb, float) and isinstance(ci_ub, float):
            self._ci_lbl.setText(f"95% CI [{ci_lb:.4f}, {ci_ub:.4f}]")
        else:
            self._ci_lbl.setText("")

        # Heterogeneity table
        stats = [
            ("I²",     result.get("I2",     "N/A")),
            ("τ²",     result.get("tau2",   "N/A")),
            ("Q",      result.get("Q",      "N/A")),
            ("Q p-val",result.get("Q_pval", "N/A")),
            ("k (studies)", result.get("k", "N/A")),
            ("Method", result.get("method", "N/A")),
        ]
        self._stats_table.setRowCount(len(stats))
        for row, (name, val) in enumerate(stats):
            self._stats_table.setItem(row, 0, QTableWidgetItem(str(name)))
            val_str = f"{val:.4f}" if isinstance(val, float) else str(val)
            self._stats_table.setItem(row, 1, QTableWidgetItem(val_str))

        # Subgroup table
        subgroups: dict = result.get("subgroups", {})
        if subgroups:
            self._subgroup_box.setVisible(True)
            self._sg_table.setRowCount(len(subgroups))
            for row, (sg_name, sg_data) in enumerate(subgroups.items()):
                vals = [
                    sg_name,
                    str(sg_data.get("k", "?")),
                    f"{sg_data.get('estimate', 'N/A'):.4f}"
                        if isinstance(sg_data.get("estimate"), float)
                        else str(sg_data.get("estimate", "N/A")),
                    f"{sg_data.get('ci_lb', 'N/A'):.4f}"
                        if isinstance(sg_data.get("ci_lb"), float)
                        else str(sg_data.get("ci_lb", "N/A")),
                    f"{sg_data.get('ci_ub', 'N/A'):.4f}"
                        if isinstance(sg_data.get("ci_ub"), float)
                        else str(sg_data.get("ci_ub", "N/A")),
                    f"{sg_data.get('I2', 'N/A'):.1f}%"
                        if isinstance(sg_data.get("I2"), float)
                        else str(sg_data.get("I2", "N/A")),
                ]
                for col, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    item.setBackground(COLOR_SUBGROUP_HEADER)
                    self._sg_table.setItem(row, col, item)
        else:
            self._subgroup_box.setVisible(False)

    def clear(self):
        self._effect_lbl.setText("—")
        self._ci_lbl.setText("")
        self._stats_table.setRowCount(0)
        self._sg_table.setRowCount(0)
        self._subgroup_box.setVisible(False)


# ---------------------------------------------------------------------------
# Forest Plot Tab (placeholder)
# ---------------------------------------------------------------------------

class _ForestTab(QWidget):
    export_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        placeholder = QLabel(
            "🌲  Forest plot requires matplotlib\n(not yet implemented)"
        )
        placeholder.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(13)
        placeholder.setFont(font)
        placeholder.setStyleSheet("color: #666;")
        layout.addWidget(placeholder, stretch=1)

        export_btn = QPushButton("Export CSV")
        export_btn.setFixedWidth(160)
        export_btn.clicked.connect(self.export_requested)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(export_btn)
        layout.addLayout(row)


# ---------------------------------------------------------------------------
# MetaPage — main widget
# ---------------------------------------------------------------------------

class MetaPage(QWidget):
    """Meta-analysis configuration and results page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project   = None
        self._result    = {}   # last parsed R JSON result
        self._data_rows: list[dict] = []
        self._worker: Optional[_MetaWorker] = None
        self._thread: Optional[QThread]     = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        """Called by the main window when a project is opened."""
        self._project = project
        self._refresh_field_combos()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Vertical)

        # ── Settings group ──────────────────────────────────────────────
        settings_box = QGroupBox("Analysis Settings")
        form = QFormLayout(settings_box)
        form.setSpacing(8)

        # Effect size field
        self._effect_combo = QComboBox()
        self._effect_combo.setMinimumWidth(200)
        form.addRow("Effect size field:", self._effect_combo)

        # SE field + auto-from-variance checkbox
        se_row = QWidget()
        se_layout = QHBoxLayout(se_row)
        se_layout.setContentsMargins(0, 0, 0, 0)
        self._se_combo = QComboBox()
        self._se_combo.setMinimumWidth(160)
        self._auto_se_chk = QCheckBox("auto from variance")
        self._auto_se_chk.toggled.connect(self._on_auto_se_toggled)
        se_layout.addWidget(self._se_combo)
        se_layout.addWidget(self._auto_se_chk)
        se_layout.addStretch()
        form.addRow("Standard error field:", se_row)

        # Analysis method
        self._method_combo = QComboBox()
        self._method_combo.addItems(["REML", "DL", "HE", "HS", "PM"])
        form.addRow("Analysis method:", self._method_combo)

        # Subgroup field
        self._subgroup_combo = QComboBox()
        self._subgroup_combo.addItem("None")
        form.addRow("Subgroup field:", self._subgroup_combo)

        # R path
        r_row = QWidget()
        r_layout = QHBoxLayout(r_row)
        r_layout.setContentsMargins(0, 0, 0, 0)
        self._rscript_edit = QLineEdit("Rscript")
        self._rscript_edit.setPlaceholderText("Path to Rscript executable")
        detect_btn = QPushButton("Detect")
        detect_btn.setFixedWidth(70)
        detect_btn.clicked.connect(self._detect_rscript)
        r_layout.addWidget(self._rscript_edit)
        r_layout.addWidget(detect_btn)
        form.addRow("R path:", r_row)

        # Run button
        self._run_btn = QPushButton("▶  Run Analysis")
        self._run_btn.setMinimumHeight(34)
        self._run_btn.setStyleSheet(
            "QPushButton { background-color: #1a73e8; color: white; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1557b0; }"
            "QPushButton:disabled { background-color: #aaa; }"
        )
        self._run_btn.clicked.connect(self._run_analysis)
        form.addRow("", self._run_btn)

        splitter.addWidget(settings_box)

        # ── Results tab widget ──────────────────────────────────────────
        self._tabs = QTabWidget()
        self._summary_tab = _SummaryTab()
        self._forest_tab  = _ForestTab()
        self._forest_tab.export_requested.connect(self._export_csv)
        self._tabs.addTab(self._summary_tab, "Summary")
        self._tabs.addTab(self._forest_tab,  "Forest Plot")
        splitter.addWidget(self._tabs)

        # ── Log area ────────────────────────────────────────────────────
        log_box = QGroupBox("R Output / Log")
        log_layout = QVBoxLayout(log_box)
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumHeight(160)
        self._log_edit.setStyleSheet(
            "QTextEdit { font-family: monospace; font-size: 11px; "
            "background: #1e1e1e; color: #d4d4d4; }"
        )
        log_layout.addWidget(self._log_edit)
        splitter.addWidget(log_box)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        root.addWidget(splitter)

    # ------------------------------------------------------------------
    # Slots / helpers
    # ------------------------------------------------------------------

    def _on_auto_se_toggled(self, checked: bool):
        self._se_combo.setEnabled(not checked)

    def _detect_rscript(self):
        """Try to auto-detect the Rscript executable."""
        import shutil
        path = shutil.which("Rscript")
        if path:
            self._rscript_edit.setText(path)
            self._log("[Detect] Found Rscript at: " + path)
        else:
            QMessageBox.warning(
                self, "Rscript Not Found",
                "Could not find Rscript in PATH.\n"
                "Please install R or enter the path manually.",
            )

    def _log(self, text: str):
        self._log_edit.append(text)
        sb = self._log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _refresh_field_combos(self):
        """Load available fields from the project's extraction templates."""
        fields: list[str] = []
        if self._project is not None:
            try:
                cur = self._project.conn.execute(
                    "SELECT schema_json FROM extraction_templates LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    schema = json.loads(row[0])
                    if isinstance(schema, list):
                        fields = [f.get("key", "") for f in schema if f.get("key")]
                    elif isinstance(schema, dict):
                        fields = list(schema.keys())
            except Exception as exc:
                self._log(f"[Warning] Could not load fields: {exc}")

        for combo in (self._effect_combo, self._se_combo):
            combo.clear()
            combo.addItems(fields if fields else ["effect_size", "std_err", "variance"])

        self._subgroup_combo.clear()
        self._subgroup_combo.addItem("None")
        self._subgroup_combo.addItems(fields)

    def _collect_data_rows(self) -> list[dict]:
        """Fetch extracted values from the DB and pivot into record dicts."""
        if self._project is None:
            return []
        try:
            cur = self._project.conn.execute(
                "SELECT record_id, field_key, value FROM extracted_values "
                "WHERE status != 'rejected'"
            )
            rows_raw = cur.fetchall()
        except Exception as exc:
            self._log(f"[Error] DB query failed: {exc}")
            return []

        pivoted: dict[str, dict] = {}
        for record_id, field_key, value in rows_raw:
            if record_id not in pivoted:
                pivoted[record_id] = {"record_id": record_id}
            pivoted[record_id][field_key] = value
        return list(pivoted.values())

    def _run_analysis(self):
        if self._thread and self._thread.isRunning():
            return

        self._result = {}
        self._summary_tab.clear()
        self._log_edit.clear()

        effect_field   = self._effect_combo.currentText()
        se_field       = self._se_combo.currentText()
        method         = self._method_combo.currentText()
        subgroup_field = self._subgroup_combo.currentText()
        if subgroup_field == "None":
            subgroup_field = None
        rscript        = self._rscript_edit.text().strip() or "Rscript"

        # Auto SE from variance
        if self._auto_se_chk.isChecked():
            se_field = "__auto_se__"

        self._data_rows = self._collect_data_rows()
        if not self._data_rows:
            QMessageBox.information(
                self, "No Data",
                "No extracted values found.\n"
                "Please run data extraction first.",
            )
            return

        # Compute SE from variance if requested
        if se_field == "__auto_se__":
            import math
            for row in self._data_rows:
                var_candidates = [k for k in row if "vari" in k.lower() or k == "variance"]
                for vc in var_candidates:
                    try:
                        row["__se__"] = str(math.sqrt(float(row[vc])))
                        break
                    except (TypeError, ValueError):
                        pass
            se_field = "__se__"

        script = _build_r_script(
            self._data_rows, effect_field, se_field, method, subgroup_field
        )
        self._log(f"[Run] Rscript={rscript}  effect={effect_field}  se={se_field}  "
                  f"method={method}  subgroup={subgroup_field or 'None'}")

        self._run_btn.setEnabled(False)
        self._worker = _MetaWorker(rscript, script)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log_line.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(lambda: self._run_btn.setEnabled(True))
        self._thread.start()

    def _on_finished(self, result: dict):
        self._result = result
        self._summary_tab.update_results(result)
        self._tabs.setCurrentIndex(0)
        self._log("[Done] Analysis complete.")

    def _on_error(self, msg: str):
        self._log(f"[Error] {msg}")
        QMessageBox.critical(self, "Analysis Error", msg)

    def _export_csv(self):
        if not self._data_rows:
            QMessageBox.information(self, "No Data", "Run the analysis first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "meta_analysis_data.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        try:
            keys = sorted({k for row in self._data_rows for k in row.keys()})
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(self._data_rows)
            self._log(f"[Export] Saved to {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))
