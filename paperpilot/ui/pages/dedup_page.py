# ui/pages/dedup_page.py - Dedup page placeholder
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
class DedupPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Deduplication"))
