"""Stand-in pictures for the template gallery when no video has been made yet (drawn here, so no licensing)."""
import math
import os
from pathlib import Path

WIDTH, HEIGHT = 720, 1280
TITLE = "Trận Bạch Đằng năm 938"
_qt_application = None


def _app() -> None:
    global _qt_application
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _qt_application = QGuiApplication([])


def _river(painter) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPolygonF

    sky = QLinearGradient(0, 0, 0, HEIGHT * 0.62)
    sky.setColorAt(0, QColor("#3b2a5a"))
    sky.setColorAt(0.6, QColor("#c8643c"))
    sky.setColorAt(1, QColor("#f2b26b"))
    painter.fillRect(0, 0, WIDTH, HEIGHT, sky)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#ffe0a3"))
    painter.drawEllipse(QPointF(WIDTH * 0.66, HEIGHT * 0.40), 70, 70)
    for color, base, amplitude, phase in (("#5b3b4f", 0.55, 90, 0.0), ("#2f2436", 0.62, 60, 1.7)):
        points = [QPointF(0, HEIGHT)]
        for step in range(0, WIDTH + 40, 40):
            points.append(QPointF(step, HEIGHT * base - amplitude * abs(math.sin(step / 150 + phase))))
        points.append(QPointF(WIDTH, HEIGHT))
        painter.setBrush(QColor(color))
        painter.drawPolygon(QPolygonF(points))
    water = QLinearGradient(0, HEIGHT * 0.66, 0, HEIGHT)
    water.setColorAt(0, QColor("#6d4a5c"))
    water.setColorAt(1, QColor("#1c1726"))
    painter.fillRect(0, int(HEIGHT * 0.66), WIDTH, HEIGHT, water)
    painter.setBrush(QColor(255, 224, 163, 90))
    for row in range(14):
        y = HEIGHT * 0.68 + row * 28
        painter.drawRect(int(WIDTH * 0.58 - row * 6), int(y), int(90 + row * 12), 4)


def _map(painter) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainterPath, QPen

    painter.fillRect(0, 0, WIDTH, HEIGHT, QColor("#e9dcc0"))
    painter.setPen(QPen(QColor(120, 96, 60, 60), 1))
    for x in range(0, WIDTH, 60):
        painter.drawLine(x, 0, x, HEIGHT)
    for y in range(0, HEIGHT, 60):
        painter.drawLine(0, y, WIDTH, y)
    coast = QPainterPath(QPointF(WIDTH * 0.15, 0))
    coast.cubicTo(WIDTH * 0.55, HEIGHT * 0.25, WIDTH * 0.10, HEIGHT * 0.55, WIDTH * 0.62, HEIGHT)
    coast.lineTo(WIDTH, HEIGHT)
    coast.lineTo(WIDTH, 0)
    coast.closeSubpath()
    painter.setPen(QPen(QColor("#6b5433"), 3))
    painter.setBrush(QColor("#b9cfd6"))
    painter.drawPath(coast)
    route = QPainterPath(QPointF(WIDTH * 0.92, HEIGHT * 0.18))
    route.cubicTo(WIDTH * 0.70, HEIGHT * 0.35, WIDTH * 0.80, HEIGHT * 0.55, WIDTH * 0.45, HEIGHT * 0.62)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor("#9b2c2c"), 6, Qt.DashLine))
    painter.drawPath(route)
    painter.setPen(QPen(QColor("#6b5433"), 3))
    center = QPointF(WIDTH * 0.25, HEIGHT * 0.82)
    painter.drawEllipse(center, 70, 70)
    for angle in range(0, 360, 45):
        radians = math.radians(angle)
        length = 90 if angle % 90 == 0 else 55
        painter.drawLine(center, QPointF(center.x() + length * math.cos(radians), center.y() + length * math.sin(radians)))


def _stakes(painter) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPolygonF

    sky = QLinearGradient(0, 0, 0, HEIGHT)
    sky.setColorAt(0, QColor("#0e1a2b"))
    sky.setColorAt(0.55, QColor("#27435e"))
    sky.setColorAt(1, QColor("#0b1320"))
    painter.fillRect(0, 0, WIDTH, HEIGHT, sky)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#e8eef5"))
    painter.drawEllipse(QPointF(WIDTH * 0.25, HEIGHT * 0.20), 55, 55)
    painter.setBrush(QColor("#1b2c40"))
    painter.drawRect(0, int(HEIGHT * 0.58), WIDTH, HEIGHT)
    painter.setBrush(QColor("#3a2a1c"))
    for index in range(11):
        x = 30 + index * 66
        top = HEIGHT * (0.52 + 0.03 * math.sin(index))
        painter.drawPolygon(QPolygonF([QPointF(x, top), QPointF(x + 14, HEIGHT * 0.78), QPointF(x - 14, HEIGHT * 0.78)]))
    painter.setBrush(QColor("#080d15"))
    for x, scale in ((WIDTH * 0.62, 1.0), (WIDTH * 0.30, 0.7)):
        y = HEIGHT * 0.50
        hull = [QPointF(x - 150 * scale, y), QPointF(x + 150 * scale, y),
                QPointF(x + 110 * scale, y + 45 * scale), QPointF(x - 110 * scale, y + 45 * scale)]
        painter.drawPolygon(QPolygonF(hull))
        painter.drawRect(int(x - 4 * scale), int(y - 220 * scale), int(8 * scale), int(220 * scale))
        painter.drawPolygon(QPolygonF([QPointF(x + 6 * scale, y - 210 * scale), QPointF(x + 120 * scale, y - 60 * scale),
                                       QPointF(x + 6 * scale, y - 60 * scale)]))
    painter.setBrush(QColor(255, 255, 255, 40))
    for row in range(18):
        painter.drawRect(0, int(HEIGHT * 0.80 + row * 14), WIDTH, 2)


_DRAWERS = (_river, _map, _stakes)


def sample_images(directory: Path) -> list[Path]:
    """Three drawn 9:16 pictures, created once and reused."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / f"sample_{index}.png" for index in range(len(_DRAWERS))]
    if all(path.is_file() for path in paths):
        return paths
    _app()
    for path, draw in zip(paths, _DRAWERS):
        image = QImage(WIDTH, HEIGHT, QImage.Format_RGB32)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        draw(painter)
        font = QFont("Segoe UI")
        font.setPixelSize(24)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 170))
        painter.drawText(QRect(0, HEIGHT - 60, WIDTH - 24, 40), Qt.AlignRight | Qt.AlignVCenter, "Ảnh minh họa mẫu")
        painter.end()
        if not image.save(str(path), "PNG"):
            raise RuntimeError("Không tạo được ảnh mẫu.")
    return paths
