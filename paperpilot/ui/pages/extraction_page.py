# ui/pages/extraction_page.py - Extraction page placeholder
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
class ExtractionPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Data Extraction"))
