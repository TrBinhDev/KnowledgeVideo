import sys

from PySide6.QtWidgets import QApplication

from core.config import setup_logging
from ui.main_window import MainWindow
from ui.styles import STYLESHEET


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
