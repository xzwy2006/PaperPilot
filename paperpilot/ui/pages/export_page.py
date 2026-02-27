# ui/pages/export_page.py - Export page placeholder
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
class ExportPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Export (RIS / Excel)"))
