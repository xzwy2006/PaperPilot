"""Main window placeholder."""
from PySide6.QtWidgets import QMainWindow, QLabel
from PySide6.QtCore import Qt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PaperPilot")
        self.setMinimumSize(1200, 800)
        label = QLabel("PaperPilot — Loading...", self)
        label.setAlignment(Qt.AlignCenter)
        self.setCentralWidget(label)
