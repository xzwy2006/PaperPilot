# ui/main_window.py - Main window with nav sidebar, record table, detail panel
from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QSplitter,
    QFrame, QStackedWidget, QFileDialog, QMessageBox,
    QPushButton, QScrollArea,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont

from paperpilot.ui.widgets.record_table import RecordTable
from paperpilot.ui.pages.import_page import ImportPage
from paperpilot.ui.pages.dedup_page import DedupPage
from paperpilot.ui.pages.screening_page import ScreeningPage
from paperpilot.ui.pages.export_page import ExportPage
from paperpilot.ui.pages.pdf_manager_page import PdfManagerPage
from paperpilot.ui.pages.extraction_page import ExtractionPage
from paperpilot.ui.pages.meta_page import MetaPage
from paperpilot.ui.pages.settings_page import SettingsPage


NAV_ITEMS = [
    ("Import",      ImportPage),
    ("Dedup",       DedupPage),
    ("Screening",   ScreeningPage),
    ("Export",      ExportPage),
    ("PDFs",        PdfManagerPage),
    ("Extraction",  ExtractionPage),
    ("Meta",        MetaPage),
    ("Settings",    SettingsPage),
]


class DetailPanel(QScrollArea):
    """Right panel showing selected record details."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignTop)
        self.setWidget(self._container)
        self._show_placeholder()

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _show_placeholder(self):
        self._clear()
        label = QLabel("Select a record to view details")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #888;")
        self._layout.addWidget(label)

    def show_record(self, record: dict):
        self._clear()

        def row(title, value):
            lbl = QLabel(f"<b>{title}:</b> {value or '--'}")
            lbl.setWordWrap(True)
            self._layout.addWidget(lbl)

        row("Title", record.get("title"))
        row("Year", record.get("year"))
        row("Journal", record.get("journal"))
        row("Authors", record.get("authors"))
        row("DOI", record.get("doi"))
        row("PMID", record.get("pmid"))

        abstract = record.get("abstract") or ""
        if abstract:
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            self._layout.addWidget(sep)
            ab_label = QLabel(f"<b>Abstract:</b><br>{abstract}")
            ab_label.setWordWrap(True)
            self._layout.addWidget(ab_label)

        self._layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self, project=None):
        super().__init__()
        self._project = project
        self._records = []
        self._decisions = {}
        self._scores = {}
        self._pdf_status = {}

        self.setWindowTitle("PaperPilot")
        self.setMinimumSize(1280, 800)

        self._build_ui()
        self._update_title()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left nav sidebar ---
        nav_widget = QWidget()
        nav_widget.setFixedWidth(140)
        nav_widget.setStyleSheet("background:#2b2b2b;")
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 8, 0, 8)
        nav_layout.setSpacing(2)

        title_lbl = QLabel("PaperPilot")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet("color:#fff; font-weight:bold; font-size:13px; padding:8px;")
        nav_layout.addWidget(title_lbl)

        self._nav_list = QListWidget()
        self._nav_list.setStyleSheet("""
            QListWidget { background:transparent; border:none; color:#ccc; }
            QListWidget::item { padding:10px 16px; border-radius:4px; margin:1px 4px; }
            QListWidget::item:selected { background:#4a9eff; color:#fff; }
            QListWidget::item:hover { background:#3a3a3a; }
        """)
        for label, _ in NAV_ITEMS:
            self._nav_list.addItem(QListWidgetItem(label))
        self._nav_list.currentRowChanged.connect(self._on_nav_change)
        nav_layout.addWidget(self._nav_list)

        # Project open button
        open_btn = QPushButton("Open Project")
        open_btn.setStyleSheet("margin:4px; padding:6px; background:#4a9eff; color:#fff; border-radius:4px; border:none;")
        open_btn.clicked.connect(self._open_project)
        nav_layout.addWidget(open_btn)

        root.addWidget(nav_widget)

        # --- Main area splitter ---
        self._splitter = QSplitter(Qt.Horizontal)
        root.addWidget(self._splitter, 1)

        # Center: stacked pages + record table
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

        # Page stack (top)
        self._page_stack = QStackedWidget()
        self._pages = []
        for _, PageClass in NAV_ITEMS:
            page = PageClass()
            self._pages.append(page)
            self._page_stack.addWidget(page)
        center_layout.addWidget(self._page_stack, 1)

        # Record table (bottom)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        center_layout.addWidget(sep)

        table_header = QLabel("Records")
        table_header.setStyleSheet("font-weight:bold; padding:4px 8px; background:#f5f5f5;")
        center_layout.addWidget(table_header)

        self._record_table = RecordTable()
        self._record_table.record_selected = self._on_record_selected
        center_layout.addWidget(self._record_table, 2)

        self._splitter.addWidget(center)

        # Right: detail panel
        self._detail_panel = DetailPanel()
        self._detail_panel.setMinimumWidth(280)
        self._splitter.addWidget(self._detail_panel)
        self._splitter.setSizes([900, 320])

        # Default nav selection
        self._nav_list.setCurrentRow(0)

    def _on_nav_change(self, row):
        if 0 <= row < len(self._pages):
            self._page_stack.setCurrentIndex(row)

    def _on_record_selected(self, record):
        self._detail_panel.show_record(record)

    def _open_project(self):
        path = QFileDialog.getExistingDirectory(self, "Open Project Folder")
        if path:
            try:
                from paperpilot.core.project import Project
                self._project = Project.open(path)
                self._update_title()
                self._load_records()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def _load_records(self):
        if not self._project:
            return
        from paperpilot.core.repositories import RecordRepository, ScreeningRepository
        rec_repo = RecordRepository(self._project.conn)
        s_repo = ScreeningRepository(self._project.conn)
        records = rec_repo.list_all()
        record_dicts = [r.model_dump() for r in records]
        decisions = {}
        for r in records:
            d = s_repo.get_latest(r.id)
            if d:
                decisions[r.id] = d.decision
        self._record_table.load(record_dicts, decisions)

    def _update_title(self):
        if self._project:
            self.setWindowTitle(f"PaperPilot -- {self._project.project_dir}")
        else:
            self.setWindowTitle("PaperPilot -- No Project Open")
