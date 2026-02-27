"""
ui/pages/screening_page.py — Screening (title/abstract) review page for PaperPilot.

Layout:  left: record list + filter  |  right: detail/decision panel
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QLabel, QPushButton,
    QTextEdit, QGroupBox, QComboBox, QMessageBox,
    QFrame, QScrollArea, QSizePolicy,
)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
COLOR_INCLUDE   = QColor("#c3e6cb")   # soft green
COLOR_EXCLUDE   = QColor("#f5c6cb")   # soft red
COLOR_MAYBE     = QColor("#fff3cd")   # soft yellow
COLOR_UNDECIDED = QColor("#e2e3e5")   # light grey

DECISION_COLORS = {
    "include": COLOR_INCLUDE,
    "exclude": COLOR_EXCLUDE,
    "maybe":   COLOR_MAYBE,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_TAXONOMY_PATH = (
    Path(__file__).parent.parent.parent / "assets" / "templates" / "reasons_taxonomy.yaml"
)
_PROTOCOL_PATH = (
    Path(__file__).parent.parent.parent / "assets" / "templates" / "protocol_default.json"
)


def _load_reasons() -> dict[str, str]:
    """Load exclusion reasons from reasons_taxonomy.yaml."""
    try:
        with _TAXONOMY_PATH.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data.get("exclusion_reasons", {})
    except Exception:
        return {
            "TA001": "Wrong study type",
            "TA002": "Wrong population",
            "TA003": "Wrong intervention",
            "TA004": "Wrong outcome",
            "TA005": "Duplicate",
            "TA006": "Non-human subjects",
            "TA007": "Clearly non-human (animal/in vitro)",
            "TA008": "Non-RCT design",
            "TA009": "Language not supported",
            "TA010": "Full text unavailable",
            "TA011": "Other",
        }


def _load_protocol() -> dict:
    """Load screening protocol (inclusion_criteria / must_exclude_terms)."""
    try:
        with _PROTOCOL_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# ScreeningPage
# ---------------------------------------------------------------------------

class ScreeningPage(QWidget):
    """Title/abstract screening page with left list + right detail panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._records: list[dict] = []
        self._current_record: Optional[dict] = None
        self._decisions: dict[str, dict] = {}   # record_id → latest decision dict
        self._history: dict[str, list[dict]] = {}  # record_id → all decisions
        self._reasons: dict[str, str] = _load_reasons()
        self._protocol: dict = _load_protocol()
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project(self, project) -> None:
        self._project = project
        self._load_data()
        self._refresh_list()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Statistics bar ────────────────────────────────────────────
        self._stats_lbl = QLabel("No project open.")
        self._stats_lbl.setStyleSheet(
            "font-size:13px; color:#333; padding:4px 8px;"
            "background:#f0f4f8; border-radius:4px;"
        )
        root.addWidget(self._stats_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#ccc;")
        root.addWidget(sep)

        # ── Main splitter ─────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Left panel
        left_box = QGroupBox("Records")
        left_layout = QVBoxLayout(left_box)
        left_layout.setSpacing(4)

        # Filter combo
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All", "undecided", "include", "exclude", "maybe"])
        self._filter_combo.currentIndexChanged.connect(self._refresh_list)
        filter_row.addWidget(self._filter_combo, 1)
        left_layout.addLayout(filter_row)

        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(False)
        self._list_widget.setSpacing(1)
        self._list_widget.currentItemChanged.connect(self._on_record_selected)
        left_layout.addWidget(self._list_widget, 1)

        splitter.addWidget(left_box)

        # Right panel (scrollable)
        right_box = QGroupBox("Screening Panel")
        right_outer_layout = QVBoxLayout(right_box)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        right_inner = QWidget()
        right_layout = QVBoxLayout(right_inner)
        right_layout.setSpacing(8)
        right_layout.setContentsMargins(4, 4, 4, 4)
        scroll_area.setWidget(right_inner)
        right_outer_layout.addWidget(scroll_area)

        # Title
        self._title_lbl = QLabel("← Select a record")
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setStyleSheet(
            "font-size:15px; font-weight:bold; color:#1a1a2e; padding:4px 0;"
        )
        right_layout.addWidget(self._title_lbl)

        # Abstract with keyword highlight
        abstract_grp = QGroupBox("Abstract")
        abstract_layout = QVBoxLayout(abstract_grp)
        self._abstract_edit = QTextEdit()
        self._abstract_edit.setReadOnly(True)
        self._abstract_edit.setMinimumHeight(160)
        self._abstract_edit.setPlaceholderText("Abstract will appear here...")
        abstract_layout.addWidget(self._abstract_edit)
        right_layout.addWidget(abstract_grp)

        # Relevance score
        score_grp = QGroupBox("Relevance Score")
        score_layout = QVBoxLayout(score_grp)
        self._score_lbl = QLabel("—")
        self._score_lbl.setStyleSheet("font-size:13px;")
        score_layout.addWidget(self._score_lbl)
        self._breakdown_lbl = QLabel("")
        self._breakdown_lbl.setWordWrap(True)
        self._breakdown_lbl.setStyleSheet("font-size:11px; color:#555;")
        score_layout.addWidget(self._breakdown_lbl)
        right_layout.addWidget(score_grp)

        # AI suggestion (placeholder)
        ai_grp = QGroupBox("AI Suggestion")
        ai_layout = QVBoxLayout(ai_grp)
        self._ai_lbl = QLabel("AI suggestion: (not yet available)")
        self._ai_lbl.setStyleSheet("font-size:12px; color:#666; font-style:italic;")
        self._ai_lbl.setWordWrap(True)
        ai_layout.addWidget(self._ai_lbl)
        right_layout.addWidget(ai_grp)

        # ── Decision buttons ──────────────────────────────────────────
        decision_grp = QGroupBox("Decision")
        decision_layout = QVBoxLayout(decision_grp)

        btn_row = QHBoxLayout()

        self._include_btn = QPushButton("✅ Include")
        self._include_btn.setStyleSheet(
            "padding:7px 18px; background:#28a745; color:#fff;"
            "border-radius:5px; border:none; font-size:13px;"
        )
        self._include_btn.clicked.connect(lambda: self._save_decision("include"))

        self._exclude_btn = QPushButton("❌ Exclude")
        self._exclude_btn.setStyleSheet(
            "padding:7px 18px; background:#dc3545; color:#fff;"
            "border-radius:5px; border:none; font-size:13px;"
        )
        self._exclude_btn.clicked.connect(lambda: self._save_decision("exclude"))

        self._maybe_btn = QPushButton("❓ Maybe")
        self._maybe_btn.setStyleSheet(
            "padding:7px 18px; background:#ffc107; color:#212529;"
            "border-radius:5px; border:none; font-size:13px;"
        )
        self._maybe_btn.clicked.connect(lambda: self._save_decision("maybe"))

        btn_row.addWidget(self._include_btn)
        btn_row.addWidget(self._exclude_btn)
        btn_row.addWidget(self._maybe_btn)
        btn_row.addStretch()
        decision_layout.addLayout(btn_row)

        # Reason combo (only active on Exclude)
        reason_row = QHBoxLayout()
        reason_row.addWidget(QLabel("Exclusion reason:"))
        self._reason_combo = QComboBox()
        self._reason_combo.addItem("— select reason —", "")
        for code, label in self._reasons.items():
            self._reason_combo.addItem(f"{code}: {label}", code)
        self._reason_combo.setEnabled(False)
        self._reason_combo.setMinimumWidth(280)
        reason_row.addWidget(self._reason_combo)
        reason_row.addStretch()
        decision_layout.addLayout(reason_row)

        right_layout.addWidget(decision_grp)

        # ── Decision history ──────────────────────────────────────────
        hist_grp = QGroupBox("Decision History")
        hist_layout = QVBoxLayout(hist_grp)
        self._history_edit = QTextEdit()
        self._history_edit.setReadOnly(True)
        self._history_edit.setMaximumHeight(120)
        self._history_edit.setPlaceholderText("Decision history will appear here...")
        hist_layout.addWidget(self._history_edit)
        right_layout.addWidget(hist_grp)

        right_layout.addStretch()

        splitter.addWidget(right_box)
        splitter.setSizes([380, 620])
        root.addWidget(splitter, 1)

        # Wire up reason combo to disable/enable
        self._exclude_btn.clicked.connect(lambda: self._reason_combo.setEnabled(True))
        self._include_btn.clicked.connect(lambda: self._reason_combo.setEnabled(False))
        self._maybe_btn.clicked.connect(lambda: self._reason_combo.setEnabled(False))

        # Initially disable all decision controls
        self._set_decision_enabled(False)

    def _set_decision_enabled(self, enabled: bool) -> None:
        for btn in (self._include_btn, self._exclude_btn, self._maybe_btn):
            btn.setEnabled(enabled)
        if not enabled:
            self._reason_combo.setEnabled(False)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self) -> None:
        """Load records and latest decisions from DB."""
        if not self._project:
            return
        conn = self._project.conn

        # Records
        rows = conn.execute(
            "SELECT * FROM records ORDER BY created_at"
        ).fetchall()
        self._records = [dict(r) for r in rows]

        # Latest decision per record
        self._decisions.clear()
        self._history.clear()
        all_dec = conn.execute(
            "SELECT * FROM screening_decisions ORDER BY ts"
        ).fetchall()
        for row in all_dec:
            d = dict(row)
            rid = d["record_id"]
            self._decisions[rid] = d          # keep last (ordered asc)
            self._history.setdefault(rid, []).append(d)

    def _get_latest_decision(self, record_id: str) -> Optional[str]:
        d = self._decisions.get(record_id)
        return d["decision"] if d else None

    # ------------------------------------------------------------------
    # List refresh
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        self._list_widget.clear()
        filter_val = self._filter_combo.currentText()

        # Stats
        total = len(self._records)
        counts: dict[str, int] = {"include": 0, "exclude": 0, "maybe": 0}
        for r in self._records:
            d = self._get_latest_decision(r["id"])
            if d in counts:
                counts[d] += 1
        undecided = total - sum(counts.values())
        self._stats_lbl.setText(
            f"Total: {total}  |  ✅ Include: {counts['include']}  |  "
            f"❌ Exclude: {counts['exclude']}  |  ❓ Maybe: {counts['maybe']}  |  "
            f"⬜ Undecided: {undecided}"
        )

        for rec in self._records:
            decision = self._get_latest_decision(rec["id"])

            # Apply filter
            if filter_val != "All":
                if filter_val == "undecided":
                    if decision is not None:
                        continue
                else:
                    if decision != filter_val:
                        continue

            title = rec.get("title") or rec["id"]
            if decision:
                label = f"[{decision.upper()}]  {title}"
            else:
                label = f"[—]  {title}"

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, rec["id"])

            color = DECISION_COLORS.get(decision, COLOR_UNDECIDED) if decision else COLOR_UNDECIDED
            item.setBackground(QBrush(color))

            self._list_widget.addItem(item)

    # ------------------------------------------------------------------
    # Record selection
    # ------------------------------------------------------------------

    def _on_record_selected(self, current: QListWidgetItem, _previous) -> None:
        if current is None:
            return
        record_id = current.data(Qt.UserRole)
        rec = next((r for r in self._records if r["id"] == record_id), None)
        if rec is None:
            return
        self._current_record = rec
        self._populate_detail(rec)
        self._set_decision_enabled(True)

    def _populate_detail(self, rec: dict) -> None:
        """Fill right panel with record details."""
        # Title
        self._title_lbl.setText(rec.get("title") or rec["id"])

        # Abstract with keyword highlighting
        abstract = rec.get("abstract") or ""
        self._set_highlighted_abstract(abstract)

        # Relevance score
        self._load_relevance_score(rec["id"])

        # AI suggestion placeholder
        self._ai_lbl.setText("AI suggestion: (not yet available)")

        # Pre-select existing reason if excluded
        dec = self._decisions.get(rec["id"])
        if dec:
            reason_code = dec.get("reason_code") or ""
            idx = self._reason_combo.findData(reason_code)
            self._reason_combo.setCurrentIndex(max(0, idx))
            self._reason_combo.setEnabled(dec["decision"] == "exclude")
        else:
            self._reason_combo.setCurrentIndex(0)
            self._reason_combo.setEnabled(False)

        # Decision history
        self._populate_history(rec["id"])

    def _set_highlighted_abstract(self, abstract: str) -> None:
        """Display abstract with must_exclude_terms in red and inclusion_criteria in green."""
        self._abstract_edit.clear()
        if not abstract:
            self._abstract_edit.setPlaceholderText("No abstract available.")
            return

        must_exclude = self._protocol.get("must_exclude_terms", [])
        inclusion_kws = self._protocol.get("inclusion_criteria", [])

        # Build regex patterns (case-insensitive)
        exclude_pats = [re.escape(t) for t in must_exclude if t]
        include_pats = [re.escape(t) for t in inclusion_kws if t]

        # Combine: exclude first (higher priority in highlighting)
        combined_pats = []
        if exclude_pats:
            combined_pats.append(("exclude", re.compile(
                r"(" + "|".join(exclude_pats) + r")", re.IGNORECASE
            )))
        if include_pats:
            combined_pats.append(("include", re.compile(
                r"(" + "|".join(include_pats) + r")", re.IGNORECASE
            )))

        # Tokenise abstract into (text, tag) segments
        # Strategy: split on a master regex, tag each segment
        if not combined_pats:
            self._abstract_edit.setPlainText(abstract)
            return

        all_pats = []
        if exclude_pats:
            all_pats.append(r"(?P<exc>" + "|".join(exclude_pats) + r")")
        if include_pats:
            all_pats.append(r"(?P<inc>" + "|".join(include_pats) + r")")
        master = re.compile("|".join(all_pats), re.IGNORECASE)

        cursor = self._abstract_edit.textCursor()
        pos = 0
        fmt_default = QTextCharFormat()
        fmt_exclude = QTextCharFormat()
        fmt_exclude.setBackground(QColor("#f5c6cb"))  # light red
        fmt_include = QTextCharFormat()
        fmt_include.setBackground(QColor("#c3e6cb"))  # light green

        for m in master.finditer(abstract):
            # Plain text before match
            if m.start() > pos:
                cursor.insertText(abstract[pos:m.start()], fmt_default)
            # Match
            if m.lastgroup == "exc":
                cursor.insertText(m.group(), fmt_exclude)
            else:
                cursor.insertText(m.group(), fmt_include)
            pos = m.end()

        # Remaining text
        if pos < len(abstract):
            cursor.insertText(abstract[pos:], fmt_default)

        self._abstract_edit.setTextCursor(cursor)
        self._abstract_edit.moveCursor(QTextCursor.Start)

    def _load_relevance_score(self, record_id: str) -> None:
        if not self._project:
            return
        row = self._project.conn.execute(
            "SELECT score_total, breakdown_json FROM relevance_scores WHERE record_id=?",
            (record_id,)
        ).fetchone()
        if row:
            total = row["score_total"]
            self._score_lbl.setText(f"Total score: <b>{total:.2f}</b>")
            try:
                bd = json.loads(row["breakdown_json"] or "{}")
                parts = [f"{k}: {v}" for k, v in bd.items()]
                self._breakdown_lbl.setText("  |  ".join(parts) if parts else "")
            except Exception:
                self._breakdown_lbl.setText("")
        else:
            self._score_lbl.setText("No score data.")
            self._breakdown_lbl.setText("")

    def _populate_history(self, record_id: str) -> None:
        history = self._history.get(record_id, [])
        if not history:
            self._history_edit.setPlainText("No previous decisions.")
            return
        lines = []
        for d in reversed(history):
            ts = d.get("ts") or d.get("created_at") or "?"
            decision = d.get("decision", "?")
            reason = d.get("reason_code") or ""
            source = d.get("source", "manual")
            parts = [f"[{ts[:19]}]", decision.upper()]
            if reason:
                label = self._reasons.get(reason, reason)
                parts.append(f"({reason}: {label})")
            parts.append(f"via {source}")
            lines.append("  ".join(parts))
        self._history_edit.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # Saving decisions
    # ------------------------------------------------------------------

    def _save_decision(self, decision: str) -> None:
        if self._current_record is None:
            return

        reason_code: Optional[str] = None

        if decision == "exclude":
            reason_code = self._reason_combo.currentData()
            if not reason_code:
                QMessageBox.warning(
                    self,
                    "Exclusion reason required",
                    "Please select an exclusion reason before marking this record as Exclude.",
                )
                self._reason_combo.setEnabled(True)
                return

        record_id = self._current_record["id"]
        new_decision = {
            "id": str(uuid.uuid4()),
            "record_id": record_id,
            "stage": "title_abstract",
            "decision": decision,
            "reason_code": reason_code,
            "evidence_snippet": None,
            "source": "manual",
            "ts": _now_iso(),
        }

        # Write to DB
        conn = self._project.conn
        conn.execute(
            "INSERT INTO screening_decisions "
            "(id, record_id, stage, decision, reason_code, evidence_snippet, source, ts) "
            "VALUES (:id, :record_id, :stage, :decision, :reason_code, "
            ":evidence_snippet, :source, :ts)",
            new_decision,
        )
        conn.commit()

        # Update in-memory caches
        self._decisions[record_id] = new_decision
        self._history.setdefault(record_id, []).append(new_decision)

        # Refresh UI
        self._populate_history(record_id)
        self._refresh_list()

        # Re-select the same record in the refreshed list
        self._reselect_record(record_id)

    def _reselect_record(self, record_id: str) -> None:
        """Find and re-select the given record in the list after refresh."""
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item and item.data(Qt.UserRole) == record_id:
                self._list_widget.blockSignals(True)
                self._list_widget.setCurrentItem(item)
                self._list_widget.blockSignals(False)
                break
