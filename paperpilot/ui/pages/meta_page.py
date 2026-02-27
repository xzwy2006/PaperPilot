# ui/pages/meta_page.py - Meta-analysis page placeholder
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
class MetaPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Meta-Analysis"))
