# ui/pages/screening_page.py - Screening page placeholder
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
class ScreeningPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Title / Abstract Screening"))
