import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel
from PySide6.QtCore import Qt


def main():
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("PaperPilot")
    window.setMinimumSize(1200, 800)
    label = QLabel("PaperPilot — Loading...", window)
    label.setAlignment(Qt.AlignCenter)
    window.setCentralWidget(label)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
