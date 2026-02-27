"""ui/pages/import_page.py — Import Records page (CSV / RIS)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QProgressDialog, QTextEdit,
    QGroupBox, QFrame,
)
from PySide6.QtCore import Qt, Signal, QThread, QObject


# ---------------------------------------------------------------------------
# Background import worker
# ---------------------------------------------------------------------------

class _ImportWorker(QObject):
    """Runs the actual import in a background QThread."""

    progress = Signal(int, int)        # (current, total)
    finished = Signal(int, int, list)  # (imported, skipped, errors)

    def __init__(self, file_path: str, fmt: str, project):
        super().__init__()
        self._path = file_path
        self._fmt = fmt
        self._project = project

    def run(self) -> None:
        from paperpilot.core.repositories import RecordRepository
        from paperpilot.core.models import Record as ModelRecord

        errors: list[str] = []
        imported = 0
        skipped = 0

        # --- Parse file ---
        try:
            if self._fmt == "csv":
                from paperpilot.core.importers.csv import import_csv
                raw_records = import_csv(self._path)
            elif self._fmt == "ris":
                from paperpilot.core.importers.ris import import_ris
                raw_records = import_ris(self._path)
            else:
                errors.append(f"Unknown format: {self._fmt}")
                self.finished.emit(0, 0, errors)
                return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Parse error: {exc}")
            self.finished.emit(0, 0, errors)
            return

        repo = RecordRepository(self._project.conn)
        total = len(raw_records)

        for i, r in enumerate(raw_records):
            # Honour thread interruption requests (e.g. Cancel button)
            if QThread.currentThread().isInterruptionRequested():
                errors.append("Import cancelled by user.")
                break

            self.progress.emit(i + 1, total)

            try:
                # Convert year string → int
                year_val: int | None = None
                raw_year = getattr(r, "year", "") or ""
                if raw_year:
                    import re
                    m = re.search(r"\b(\d{4})\b", str(raw_year))
                    if m:
                        year_val = int(m.group(1))

                fingerprint: str = getattr(r, "title_norm", "") or ""
                doi: str = (getattr(r, "doi", "") or "").strip()

                # --- Dedup checks ---
                if fingerprint and repo.get_by_fingerprint(fingerprint):
                    skipped += 1
                    continue
                if doi and repo.get_by_doi(doi):
                    skipped += 1
                    continue

                model_rec = ModelRecord(
                    title=getattr(r, "title", None) or None,
                    title_norm=fingerprint or None,
                    abstract=getattr(r, "abstract", None) or None,
                    authors=getattr(r, "authors", None) or None,
                    year=year_val,
                    journal=getattr(r, "journal", None) or None,
                    doi=doi or None,
                    pmid=getattr(r, "pmid", None) or None,
                    keywords=getattr(r, "keywords", None) or None,
                    fingerprint=fingerprint or None,
                    raw_import_blob=getattr(r, "raw_import_blob", None) or None,
                )
                repo.insert(model_rec)
                imported += 1

            except Exception as exc:  # noqa: BLE001
                errors.append(f"Row {i + 1}: {exc}")

        self.finished.emit(imported, skipped, errors)


# ---------------------------------------------------------------------------
# Import page widget
# ---------------------------------------------------------------------------

class ImportPage(QWidget):
    """Page that lets the user import records from CSV or RIS files."""

    records_imported = Signal()  # emitted after at least one record is imported

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._thread: QThread | None = None
        self._worker: _ImportWorker | None = None
        self._progress: QProgressDialog | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignTop)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        # Header
        header = QLabel("Import Records")
        header.setStyleSheet(
            "font-size:18px; font-weight:bold; color:#1a1a2e;"
        )
        root.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#ddd;")
        root.addWidget(sep)

        # Project status
        self._status_lbl = QLabel("Please open a project first.")
        self._status_lbl.setStyleSheet("color:#999; font-style:italic;")
        root.addWidget(self._status_lbl)

        # --- Import buttons group ---
        btn_box = QGroupBox("Import Source")
        btn_layout = QHBoxLayout(btn_box)
        btn_layout.setSpacing(14)

        self._csv_btn = QPushButton("📄  Import CSV")
        self._csv_btn.setFixedHeight(46)
        self._csv_btn.setStyleSheet(self._btn_style("#4a9eff", "#3a8ef0", "#a8caff"))
        self._csv_btn.clicked.connect(lambda: self._start_import("csv"))
        btn_layout.addWidget(self._csv_btn)

        self._ris_btn = QPushButton("📑  Import RIS")
        self._ris_btn.setFixedHeight(46)
        self._ris_btn.setStyleSheet(self._btn_style("#5cb85c", "#4cae4c", "#aadaaa"))
        self._ris_btn.clicked.connect(lambda: self._start_import("ris"))
        btn_layout.addWidget(self._ris_btn)

        btn_layout.addStretch()
        root.addWidget(btn_box)

        # Hint text
        hint = QLabel(
            "Supported formats: <b>CSV</b> (Web of Science, Scopus, PubMed exports) "
            "· <b>RIS</b> (Mendeley, Zotero, EndNote exports).<br>"
            "Duplicate records (matched by title fingerprint or DOI) are automatically skipped."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:12px;")
        root.addWidget(hint)

        # --- Results box ---
        result_box = QGroupBox("Import Results")
        result_layout = QVBoxLayout(result_box)
        self._result_edit = QTextEdit()
        self._result_edit.setReadOnly(True)
        self._result_edit.setFixedHeight(200)
        self._result_edit.setStyleSheet(
            "font-family: monospace; font-size: 12px; background:#fafafa; border:none;"
        )
        self._result_edit.setPlaceholderText("Import results will appear here…")
        result_layout.addWidget(self._result_edit)
        root.addWidget(result_box)

        root.addStretch()

        # Initial button state
        self._set_buttons_enabled(False)

    @staticmethod
    def _btn_style(normal: str, hover: str, disabled: str) -> str:
        return (
            f"QPushButton {{ font-size:14px; background:{normal}; color:#fff;"
            f" border:none; border-radius:6px; padding:8px 22px; }}"
            f"QPushButton:hover {{ background:{hover}; }}"
            f"QPushButton:disabled {{ background:{disabled}; color:#eee; }}"
        )

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._csv_btn.setEnabled(enabled)
        self._ris_btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        """Called by MainWindow when a project is opened (or closed)."""
        self._project = project
        if project:
            self._status_lbl.setText(
                f"Project: \u202a{project.project_dir.name}\u202c  \u2713  Ready to import."
            )
            self._status_lbl.setStyleSheet("color:#2a7a2a; font-style:normal; font-weight:bold;")
            self._set_buttons_enabled(True)
        else:
            self._status_lbl.setText("Please open a project first.")
            self._status_lbl.setStyleSheet("color:#999; font-style:italic;")
            self._set_buttons_enabled(False)

    # ------------------------------------------------------------------
    # Import flow
    # ------------------------------------------------------------------

    def _start_import(self, fmt: str) -> None:
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return

        # File dialog
        if fmt == "csv":
            caption = "Select CSV File"
            file_filter = "CSV Files (*.csv);;All Files (*)"
        else:
            caption = "Select RIS File"
            file_filter = "RIS Files (*.ris *.txt);;All Files (*)"

        file_path, _ = QFileDialog.getOpenFileName(self, caption, "", file_filter)
        if not file_path:
            return

        self._set_buttons_enabled(False)
        self._result_edit.clear()

        # Progress dialog (indeterminate until first record arrives)
        self._progress = QProgressDialog("Preparing import…", "Cancel", 0, 0, self)
        self._progress.setWindowTitle("Importing")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setMinimumWidth(380)
        self._progress.show()

        # Worker + thread
        self._thread = QThread(self)
        self._worker = _ImportWorker(file_path, fmt, self._project)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        # Cancel button hooks thread interruption
        self._progress.canceled.connect(
            lambda: self._thread.requestInterruption() if self._thread else None
        )

        self._thread.start()

    def _on_progress(self, current: int, total: int) -> None:
        if self._progress:
            self._progress.setMaximum(total)
            self._progress.setValue(current)
            self._progress.setLabelText(
                f"Processing record {current} / {total}…"
            )

    def _on_finished(self, imported: int, skipped: int, errors: list) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None

        self._set_buttons_enabled(True)

        lines = [
            f"✅  Imported:           {imported}",
            f"⏭   Skipped (duplicates): {skipped}",
        ]
        if errors:
            lines.append(f"\n⚠️  Errors ({len(errors)}):")
            for err in errors[:25]:
                lines.append(f"   • {err}")
            if len(errors) > 25:
                lines.append(f"   … and {len(errors) - 25} more.")

        self._result_edit.setPlainText("\n".join(lines))

        if imported > 0:
            self.records_imported.emit()
