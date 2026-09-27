"""History title cards drawn with Qt (full-frame transparent PNG overlaid while the hook is read).

Qt shapes Vietnamese text correctly and allows richer layouts than ffmpeg drawtext.
"""
import os
import random
from pathlib import Path

HISTORY_TEMPLATES = {
    "history-scroll": "Cổ thư (giấy da, tông sepia)",
    "history-imperial": "Hoàng triều (đỏ son, vàng kim)",
    "history-archive": "Tư liệu (đen trắng, khung phim)",
}

# ffmpeg filters appended to every scene; each ends with "," because it is spliced into a filter chain.
HISTORY_GRADES = {
    "history-scroll": "hue=s=0.45,colorbalance=rs=.10:gs=.03:bs=-.10:rm=.06:bm=-.06,",
    "history-imperial": "colorbalance=rs=.06:gs=.01:bs=-.05,eq=contrast=1.05:saturation=1.08,",
    "history-archive": "hue=s=0,colorbalance=rs=.08:gs=.03:bs=-.06,vignette=PI/5,noise=alls=8:allf=t,",
}

_SERIF_FILES = ("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf")
_families: dict[str, str] = {}
_qt_application = None


def _serif_family() -> str:
    global _qt_application
    from PySide6.QtGui import QFontDatabase, QGuiApplication

    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _qt_application = QGuiApplication([])
    if "serif" not in _families:
        family = "Times New Roman"
        for path in (os.environ.get("KV_SERIF_FONT") or "", *_SERIF_FILES):
            if path and Path(path).is_file():
                loaded = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(path))
                family = loaded[0] if loaded else family
        _families["serif"] = family
    return _families["serif"]


def _font(size_px: float, bold: bool = False, spacing: float = 0.0):
    from PySide6.QtGui import QFont

    font = QFont(_serif_family())
    font.setPixelSize(max(8, round(size_px)))
    font.setBold(bold)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return font


def _fit_text(painter, text: str, rect, max_px: float, min_px: float, bold: bool, flags) -> None:
    """Draw wrapped text at the largest size (max_px..min_px) that fits inside rect."""
    size = max_px
    while size > min_px:
        painter.setFont(_font(size, bold))
        if painter.boundingRect(rect, flags, text).height() <= rect.height():
            break
        size -= 2
    painter.setFont(_font(size, bold))
    painter.drawText(rect, flags, text)


def _scroll(painter, width, height, s, title, badge, label):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPen

    body = QRectF(width * 0.08, height * 0.50, width * 0.84, height * 0.30)
    parchment = QLinearGradient(0, body.top(), 0, body.bottom())
    parchment.setColorAt(0, QColor("#f5e6c4"))
    parchment.setColorAt(1, QColor("#e3c68e"))
    painter.fillRect(body, parchment)
    texture = random.Random(7)
    for _ in range(70):
        y = body.top() + texture.random() * body.height()
        painter.setPen(QPen(QColor(139, 90, 43, texture.randint(10, 28)), 1.2 * s))
        start = body.left() + texture.random() * body.width() * 0.6
        painter.drawLine(QPointF(start, y), QPointF(start + body.width() * (0.15 + texture.random() * 0.35), y))
    painter.setPen(QPen(QColor("#7a4a21"), 3 * s))
    painter.drawRect(body.adjusted(14 * s, 14 * s, -14 * s, -14 * s))
    painter.setPen(QPen(QColor("#7a4a21"), 1.2 * s))
    painter.drawRect(body.adjusted(22 * s, 22 * s, -22 * s, -22 * s))
    for y in (body.top() - 22 * s, body.bottom() - 18 * s):
        roller = QRectF(width * 0.05, y, width * 0.90, 40 * s)
        wood = QLinearGradient(0, roller.top(), 0, roller.bottom())
        wood.setColorAt(0, QColor("#5c3317"))
        wood.setColorAt(0.5, QColor("#b07a3f"))
        wood.setColorAt(1, QColor("#5c3317"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(wood)
        painter.drawRoundedRect(roller, 20 * s, 20 * s)
    painter.setPen(QColor("#8b5a2b"))
    painter.setFont(_font(26 * s, True, 4 * s))
    painter.drawText(QRectF(body.left(), body.top() + 40 * s, body.width(), 40 * s), Qt.AlignCenter, label)
    painter.setPen(QColor("#3b2412"))
    _fit_text(painter, title, QRectF(body.left() + 60 * s, body.top() + 95 * s, body.width() - 120 * s,
                                     body.height() - 140 * s), 72 * s, 34 * s, True, Qt.AlignCenter | Qt.TextWordWrap)
    if badge:
        radius = 78 * s
        painter.save()
        painter.translate(body.right() - 40 * s, body.top() - 10 * s)
        painter.rotate(-8)
        painter.setPen(QPen(QColor("#f8e7c9"), 3 * s))
        painter.setBrush(QColor(163, 29, 29, 235))
        painter.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
        painter.setPen(QColor("#fff4e0"))
        painter.setFont(_font(44 * s, True))
        painter.drawText(QRectF(-radius, -radius, radius * 2, radius * 2), Qt.AlignCenter, badge)
        painter.restore()


def _imperial(painter, width, height, s, title, badge, label):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPen, QPolygonF

    shade = QLinearGradient(0, 0, 0, height * 0.18)
    shade.setColorAt(0, QColor(0, 0, 0, 140))
    shade.setColorAt(1, QColor(0, 0, 0, 0))
    painter.fillRect(QRectF(0, 0, width, height * 0.18), shade)
    band = QRectF(width * 0.05, height * 0.56, width * 0.90, height * 0.26)
    painter.fillRect(band, QColor(122, 15, 20, 238))
    gold = QColor("#d9ad4a")
    painter.setPen(QPen(gold, 5 * s))
    painter.drawRect(band.adjusted(10 * s, 10 * s, -10 * s, -10 * s))
    painter.setPen(QPen(gold, 1.6 * s))
    painter.drawRect(band.adjusted(22 * s, 22 * s, -22 * s, -22 * s))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gold)
    size = 16 * s
    for corner in (band.topLeft(), band.topRight(), band.bottomLeft(), band.bottomRight()):
        x = corner.x() + (16 * s if corner.x() < width / 2 else -16 * s)
        y = corner.y() + (16 * s if corner.y() < height * 0.69 else -16 * s)
        painter.drawPolygon(QPolygonF([QPointF(x, y - size), QPointF(x + size, y), QPointF(x, y + size), QPointF(x - size, y)]))
    painter.setPen(gold)
    painter.setFont(_font(26 * s, True, 5 * s))
    painter.drawText(QRectF(band.left(), band.top() + 42 * s, band.width(), 40 * s), Qt.AlignCenter, f"—  {label}  —")
    painter.setPen(QColor("#f6d98a"))
    _fit_text(painter, title, QRectF(band.left() + 60 * s, band.top() + 95 * s, band.width() - 120 * s,
                                     band.height() - 130 * s), 70 * s, 32 * s, True, Qt.AlignCenter | Qt.TextWordWrap)
    if badge:
        pill = QRectF(width / 2 - 120 * s, band.top() - 34 * s, 240 * s, 68 * s)
        painter.setPen(QPen(gold, 3 * s))
        painter.setBrush(QColor(122, 15, 20, 250))
        painter.drawRoundedRect(pill, 34 * s, 34 * s)
        painter.setPen(QColor("#f6d98a"))
        painter.setFont(_font(40 * s, True, 2 * s))
        painter.drawText(pill, Qt.AlignCenter, badge)


def _archive(painter, width, height, s, title, badge, label):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPen

    fade = QLinearGradient(0, height * 0.42, 0, height * 0.93)
    fade.setColorAt(0, QColor(0, 0, 0, 0))
    fade.setColorAt(1, QColor(0, 0, 0, 225))
    painter.fillRect(QRectF(0, height * 0.42, width, height * 0.51), fade)
    bar = height * 0.075
    for top in (0.0, height - bar):
        painter.fillRect(QRectF(0, top, width, bar), QColor(8, 8, 8, 245))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(215, 215, 215, 210))
        hole_w, hole_h, step = 34 * s, 50 * s, 64 * s
        x = 18 * s
        while x + hole_w < width:
            painter.drawRoundedRect(QRectF(x, top + (bar - hole_h) / 2, hole_w, hole_h), 6 * s, 6 * s)
            x += step
    left = width * 0.08
    amber = QColor("#f0b429")
    painter.setPen(amber)
    painter.setFont(_font(28 * s, True, 6 * s))
    painter.drawText(QRectF(left, height * 0.58, width * 0.84, 44 * s), Qt.AlignLeft | Qt.AlignVCenter, label)
    y = height * 0.58 + 56 * s
    if badge:
        painter.setPen(QColor("#ffffff"))
        painter.setFont(_font(150 * s, True))
        painter.drawText(QRectF(left, y, width * 0.84, 170 * s), Qt.AlignLeft | Qt.AlignVCenter, badge)
        y += 180 * s
    painter.setPen(QPen(amber, 4 * s))
    painter.drawLine(QPointF(left, y), QPointF(left + 160 * s, y))
    painter.setPen(QColor("#f5f5f5"))
    _fit_text(painter, title, QRectF(left, y + 24 * s, width * 0.84, height * 0.86 - (y + 24 * s)),
              64 * s, 30 * s, True, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)


_DRAWERS = {"history-scroll": _scroll, "history-imperial": _imperial, "history-archive": _archive}


def render_title_card(template: str, title: str, badge: str, label: str, width: int, height: int, output: Path) -> Path:
    from PySide6.QtGui import QImage, QPainter

    _serif_family()
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    _DRAWERS[template](painter, width, height, width / 1080, " ".join(title.split()), badge, label.upper())
    painter.end()
    if not image.save(str(output), "PNG"):
        raise RuntimeError("Không tạo được thẻ tiêu đề lịch sử.")
    return output
