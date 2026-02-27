"""
ui/pages/pdf_manager_page.py — PDF Management page for PaperPilot.

Layout:
  Top:    Stats bar (with PDF / without PDF / total) + Batch Import button
  Middle: QTableWidget (Title | Year | DOI | PDF Status | PDF Path | Action)
  Bottom: PDF preview placeholder
"""
from __future__ import annotations

import os
import platform
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QFrame, QProgressDialog, QSizePolicy,
)
from PySide6.QtGui import QColor, QBrush


# ---------------------------------------------------------------------------
# PDFManager — thin wrapper around the pdf_files table
# ---------------------------------------------------------------------------

class PDFManager:
    """CRUD helper for the pdf_files table."""

    def __init__(self, conn):
        self.conn = conn

    # ------------------------------------------------------------------
    def link_pdf(self, record_id: str, file_path: str) -> dict:
        """Insert or update a pdf_files row linking a record to a PDF."""
        # Check if a link already exists for this record
        row = self.conn.execute(
            "SELECT id FROM pdf_files WHERE record_id = ?", (record_id,)
        ).fetchone()

        now = datetime.utcnow().isoformat()
        if row:
            pdf_id = row["id"]
            self.conn.execute(
                "UPDATE pdf_files SET file_path=?, linked_at=? WHERE id=?",
                (file_path, now, pdf_id),
            )
        else:
            pdf_id = str(uuid.uuid4())
            self.conn.execute(
                """INSERT INTO pdf_files (id, record_id, file_path, linked_at)
                   VALUES (?, ?, ?, ?)""",
                (pdf_id, record_id, file_path, now),
            )
        self.conn.commit()
        return {"id": pdf_id, "record_id": record_id, "file_path": file_path}

    def get_pdf(self, record_id: str) -> Optional[str]:
        """Return the file_path for a record's PDF, or None."""
        row = self.conn.execute(
            "SELECT file_path FROM pdf_files WHERE record_id = ?", (record_id,)
        ).fetchone()
        return row["file_path"] if row else None

    def all_links(self) -> list[dict]:
        """Return all pdf_files rows as dicts."""
        rows = self.conn.execute("SELECT * FROM pdf_files").fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_file_manager(file_path: str) -> None:
    """Open file manager to show the given file."""
    p = Path(file_path)
    if not p.exists():
        return
    system = platform.system()
    if system == "Windows":
        os.startfile(str(p.parent))
    elif system == "Darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:  # Linux / BSD
        subprocess.Popen(["xdg-open", str(p.parent)])


def _fuzzy_match_records(pdf_names: list[str], records: list[dict],
                          threshold: float = 60.0) -> dict[str, dict]:
    """
    Return {pdf_filename: record_dict} for best fuzzy matches above threshold.
    Uses rapidfuzz if available, otherwise falls back to difflib.
    """
    try:
        from rapidfuzz import process as rp, fuzz
        use_rapidfuzz = True
    except ImportError:
        import difflib
        use_rapidfuzz = False

    titles = [r.get("title") or "" for r in records]
    matched: dict[str, dict] = {}

    for pdf_name in pdf_names:
        stem = Path(pdf_name).stem.replace("_", " ").replace("-", " ")

        if use_rapidfuzz:
            result = rp.extractOne(stem, titles, scorer=fuzz.WRatio, score_cutoff=threshold)
            if result:
                best_title, score, idx = result
                matched[pdf_name] = records[idx]
        else:
            close = difflib.get_close_matches(stem, titles, n=1, cutoff=threshold / 100.0)
            if close:
                idx = titles.index(close[0])
                matched[pdf_name] = records[idx]

    return matched


# ---------------------------------------------------------------------------
# PDFManagerPage
# ---------------------------------------------------------------------------

class PDFManagerPage(QWidget):
    """PDF management page: link PDFs to records, batch import, preview."""

    # Table column indices
    COL_TITLE  = 0
    COL_YEAR   = 1
    COL_DOI    = 2
    COL_STATUS = 3
    COL_PATH   = 4
    COL_ACTION = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._records: list[dict] = []
        self._pdf_map: dict[str, str] = {}   # record_id → file_path
        self._pdf_manager: Optional[PDFManager] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        self._project = project
        self._pdf_manager = PDFManager(project.conn)
        self._load_data()
        self._refresh_table()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Top bar: stats + batch import ────────────────────────────
        top_bar = QHBoxLayout()

        self._stats_lbl = QLabel("No project open.")
        self._stats_lbl.setStyleSheet(
            "font-size:13px; color:#333; padding:4px 8px;"
            "background:#f0f4f8; border-radius:4px;"
        )
        top_bar.addWidget(self._stats_lbl, 1)

        self._batch_btn = QPushButton("📂 Batch Import PDFs")
        self._batch_btn.setStyleSheet(
            "padding:6px 16px; background:#0d6efd; color:#fff;"
            "border-radius:5px; border:none; font-size:13px;"
        )
        self._batch_btn.clicked.connect(self._on_batch_import)
        self._batch_btn.setEnabled(False)
        top_bar.addWidget(self._batch_btn)

        root.addLayout(top_bar)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#ccc;")
        root.addWidget(sep)

        # ── Middle: records table ─────────────────────────────────────
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Title", "Year", "DOI", "PDF", "PDF Path", "Action"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._on_double_click)
        root.addWidget(self._table, 1)

        # ── Bottom: PDF preview placeholder ──────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color:#ccc;")
        root.addWidget(sep2)

        self._preview_lbl = QLabel("PDF preview not available")
        self._preview_lbl.setAlignment(Qt.AlignCenter)
        self._preview_lbl.setMinimumHeight(80)
        self._preview_lbl.setStyleSheet(
            "font-size:13px; color:#888; font-style:italic;"
            "background:#fafafa; border:1px dashed #ccc; border-radius:4px;"
        )
        self._preview_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self._preview_lbl)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self) -> None:
        if not self._project:
            return
        conn = self._project.conn

        rows = conn.execute(
            "SELECT id, title, year, doi FROM records ORDER BY year DESC, title"
        ).fetchall()
        self._records = [dict(r) for r in rows]

        # Build record_id → file_path map
        self._pdf_map.clear()
        pdf_rows = conn.execute("SELECT record_id, file_path FROM pdf_files").fetchall()
        for pr in pdf_rows:
            self._pdf_map[pr["record_id"]] = pr["file_path"]

    # ------------------------------------------------------------------
    # Table refresh
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        self._table.setRowCount(0)

        total   = len(self._records)
        has_pdf = sum(1 for r in self._records if r["id"] in self._pdf_map)
        no_pdf  = total - has_pdf

        self._stats_lbl.setText(
            f"Total: {total}  |  ✅ With PDF: {has_pdf}  |  ❌ Without PDF: {no_pdf}"
        )
        self._batch_btn.setEnabled(self._project is not None)

        for row_idx, rec in enumerate(self._records):
            self._table.insertRow(row_idx)
            rid = rec["id"]

            # Title
            title_item = QTableWidgetItem(rec.get("title") or "—")
            title_item.setData(Qt.UserRole, rid)
            self._table.setItem(row_idx, self.COL_TITLE, title_item)

            # Year
            year_str = str(rec["year"]) if rec.get("year") else "—"
            self._table.setItem(row_idx, self.COL_YEAR, QTableWidgetItem(year_str))

            # DOI
            doi_str = rec.get("doi") or "—"
            self._table.setItem(row_idx, self.COL_DOI, QTableWidgetItem(doi_str))

            # PDF status
            pdf_path = self._pdf_map.get(rid)
            has = pdf_path is not None
            status_item = QTableWidgetItem("✅" if has else "❌")
            status_item.setTextAlignment(Qt.AlignCenter)
            if has:
                status_item.setForeground(QBrush(QColor("#28a745")))
            else:
                status_item.setForeground(QBrush(QColor("#dc3545")))
            self._table.setItem(row_idx, self.COL_STATUS, status_item)

            # PDF path
            path_item = QTableWidgetItem(pdf_path or "—")
            path_item.setForeground(QBrush(QColor("#555") if pdf_path else QColor("#aaa")))
            self._table.setItem(row_idx, self.COL_PATH, path_item)

            # Action button
            if has:
                btn = QPushButton("📄 Open")
                btn.setStyleSheet(
                    "padding:3px 10px; background:#17a2b8; color:#fff;"
                    "border-radius:4px; border:none;"
                )
                btn.clicked.connect(lambda checked, p=pdf_path: _open_file_manager(p))
            else:
                btn = QPushButton("🔗 Link PDF")
                btn.setStyleSheet(
                    "padding:3px 10px; background:#6c757d; color:#fff;"
                    "border-radius:4px; border:none;"
                )
                btn.clicked.connect(lambda checked, r=rid: self._on_link_pdf(r))

            self._table.setCellWidget(row_idx, self.COL_ACTION, btn)

        self._table.resizeRowsToContents()

    # ------------------------------------------------------------------
    # Slot: Link PDF (single record)
    # ------------------------------------------------------------------

    def _on_link_pdf(self, record_id: str) -> None:
        if not self._pdf_manager:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PDF", "", "PDF Files (*.pdf)"
        )
        if not file_path:
            return
        try:
            self._pdf_manager.link_pdf(record_id, file_path)
            self._pdf_map[record_id] = file_path
            self._refresh_table()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to link PDF:\n{exc}")

    # ------------------------------------------------------------------
    # Slot: Batch Import PDFs
    # ------------------------------------------------------------------

    def _on_batch_import(self) -> None:
        if not self._pdf_manager:
            return

        files, _ = QFileDialog.getOpenFileNames(
            self, "Select PDF Files", "", "PDF Files (*.pdf)"
        )
        if not files:
            return

        pdf_names = [Path(f).name for f in files]
        matched = _fuzzy_match_records(pdf_names, self._records)

        if not matched:
            QMessageBox.information(
                self, "No Matches",
                "Could not fuzzy-match any selected PDF to a record title.\n"
                "Tip: rename files to resemble paper titles."
            )
            return

        # Show summary
        lines = [f"• {pdf} → {rec.get('title', '?')[:60]}"
                 for pdf, rec in matched.items()]
        confirm = QMessageBox.question(
            self, "Batch Import — Confirm",
            f"Will link {len(matched)} PDF(s):\n\n" + "\n".join(lines[:20]) +
            ("\n…" if len(lines) > 20 else "") +
            "\n\nProceed?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if confirm != QMessageBox.Yes:
            return

        # Map pdf_name back to full path
        name_to_path = {Path(f).name: f for f in files}

        progress = QProgressDialog(
            "Linking PDFs…", "Cancel", 0, len(matched), self
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        errors: list[str] = []
        for idx, (pdf_name, rec) in enumerate(matched.items()):
            if progress.wasCanceled():
                break
            progress.setValue(idx)
            full_path = name_to_path.get(pdf_name, "")
            if not full_path:
                continue
            try:
                self._pdf_manager.link_pdf(rec["id"], full_path)
                self._pdf_map[rec["id"]] = full_path
            except Exception as exc:
                errors.append(f"{pdf_name}: {exc}")

        progress.setValue(len(matched))
        self._refresh_table()

        msg = f"Linked {len(matched) - len(errors)} PDF(s) successfully."
        if errors:
            msg += f"\n\nErrors ({len(errors)}):\n" + "\n".join(errors[:10])
        QMessageBox.information(self, "Batch Import Complete", msg)

    # ------------------------------------------------------------------
    # Slot: Double-click → open file manager
    # ------------------------------------------------------------------

    def _on_double_click(self, index) -> None:
        row = index.row()
        title_item = self._table.item(row, self.COL_TITLE)
        if title_item is None:
            return
        record_id = title_item.data(Qt.UserRole)
        pdf_path = self._pdf_map.get(record_id)
        if pdf_path:
            _open_file_manager(pdf_path)
        else:
            QMessageBox.information(
                self, "No PDF",
                "This record has no linked PDF. Use 'Link PDF' to add one."
            )
