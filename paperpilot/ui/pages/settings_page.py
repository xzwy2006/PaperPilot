# ui/pages/settings_page.py - Settings page placeholder
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Settings"))
