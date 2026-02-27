# ui/pages/import_page.py - Import page placeholder
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
class ImportPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Import Records (CSV / RIS)"))
