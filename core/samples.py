"""Plain colour pictures the template gallery previews are built from (drawn here, so no licensing)."""
import os
from pathlib import Path

WIDTH, HEIGHT = 720, 1280
TITLE = "Trận Bạch Đằng năm 938"
# Top and bottom colour of each picture: warm, sepia and cool, so grades and transitions are easy to tell apart.
_GRADIENTS = (("#c8643c", "#3b2a5a"), ("#e9dcc0", "#8a6a3e"), ("#27435e", "#0b1320"))
_qt_application = None


def _app() -> None:
    global _qt_application
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _qt_application = QGuiApplication([])


def sample_images(directory: Path) -> list[Path]:
    """Three 9:16 gradient pictures, created once and reused."""
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter

    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / f"diagonal_{index}.png" for index in range(len(_GRADIENTS))]
    if all(path.is_file() for path in paths):
        return paths
    _app()
    for path, (top, bottom) in zip(paths, _GRADIENTS):
        image = QImage(WIDTH, HEIGHT, QImage.Format_RGB32)
        painter = QPainter(image)
        # Diagonal, so a horizontal-only transition (hblur) still changes the picture.
        gradient = QLinearGradient(0, 0, WIDTH, HEIGHT)
        gradient.setColorAt(0, QColor(top))
        gradient.setColorAt(1, QColor(bottom))
        painter.fillRect(0, 0, WIDTH, HEIGHT, gradient)
        painter.end()
        if not image.save(str(path), "PNG"):
            raise RuntimeError("Không tạo được ảnh mẫu.")
    return paths
