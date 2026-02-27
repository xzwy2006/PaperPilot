# ui/widgets/record_table.py - Record table widget with sort and filter
from __future__ import annotations

from typing import Optional, List
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView,
    QLineEdit, QComboBox, QLabel, QHeaderView, QCheckBox,
)
from PySide6.QtCore import Qt, QSortFilterProxyModel, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor


DECISION_COLORS = {
    "include": QColor("#d4edda"),
    "exclude": QColor("#f8d7da"),
    "maybe":   QColor("#fff3cd"),
}

COLUMNS = ["Title", "Year", "Journal", "Decision", "Score", "PDF"]


class RecordTableModel(QAbstractTableModel):
    def __init__(self, records=None, decisions=None, scores=None, pdf_status=None):
        super().__init__()
        self._records = records or []
        self._decisions = decisions or {}   # record_id -> decision str
        self._scores = scores or {}         # record_id -> float
        self._pdf_status = pdf_status or {} # record_id -> bool

    def rowCount(self, parent=QModelIndex()):
        return len(self._records)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        rec = self._records[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0: return rec.get("title", "")[:80]
            if col == 1: return str(rec.get("year", ""))
            if col == 2: return rec.get("journal", "")[:40]
            if col == 3: return self._decisions.get(rec["id"], "")
            if col == 4:
                score = self._scores.get(rec["id"])
                return f"{score:.1f}" if score is not None else ""
            if col == 5: return "Y" if self._pdf_status.get(rec["id"]) else ""

        if role == Qt.BackgroundRole and col == 3:
            decision = self._decisions.get(rec["id"], "")
            return DECISION_COLORS.get(decision)

        if role == Qt.UserRole:
            return rec

        return None

    def load(self, records, decisions=None, scores=None, pdf_status=None):
        self.beginResetModel()
        self._records = records
        self._decisions = decisions or {}
        self._scores = scores or {}
        self._pdf_status = pdf_status or {}
        self.endResetModel()

    def get_record(self, row: int):
        if 0 <= row < len(self._records):
            return self._records[row]
        return None


class RecordTable(QWidget):
    """Record table widget with sort, filter, and selection signal."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = RecordTableModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # search all columns

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Filter bar
        filter_bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search title / abstract...")
        self._search.textChanged.connect(self._proxy.setFilterFixedString)

        self._decision_filter = QComboBox()
        self._decision_filter.addItems(["All", "include", "exclude", "maybe", "(none)"])
        self._decision_filter.currentTextChanged.connect(self._apply_decision_filter)

        self._pdf_filter = QCheckBox("Has PDF")
        self._pdf_filter.stateChanged.connect(self._refresh_filter)

        filter_bar.addWidget(QLabel("Filter:"))
        filter_bar.addWidget(self._search, 3)
        filter_bar.addWidget(QLabel("Decision:"))
        filter_bar.addWidget(self._decision_filter)
        filter_bar.addWidget(self._pdf_filter)
        layout.addLayout(filter_bar)

        # Table
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(COLUMNS)):
            self._table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        layout.addWidget(self._table)

        self._table.selectionModel().currentRowChanged.connect(self._on_row_changed)

    def load(self, records, decisions=None, scores=None, pdf_status=None):
        self._model.load(records, decisions, scores, pdf_status)

    def _apply_decision_filter(self, text):
        self._refresh_filter()

    def _refresh_filter(self):
        # Custom filtering via proxy - simple re-filter by search text
        self._proxy.setFilterFixedString(self._search.text())

    def _on_row_changed(self, current, previous):
        src_index = self._proxy.mapToSource(current)
        rec = self._model.get_record(src_index.row())
        if rec:
            self.record_selected(rec)

    def record_selected(self, record):
        """Override or connect to handle record selection."""
        pass

    @property
    def table(self):
        return self._table
