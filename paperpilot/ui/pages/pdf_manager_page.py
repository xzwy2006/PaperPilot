# ui/pages/pdf_manager_page.py - PDF manager page placeholder
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
class PdfManagerPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("PDF Manager"))
