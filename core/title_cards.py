"""History title cards drawn with Qt (full-frame transparent PNG overlaid while the hook is read).

Qt shapes Vietnamese text correctly and allows richer layouts than ffmpeg drawtext.
"""
import os
from pathlib import Path

HISTORY_TEMPLATES = {
    "history-scroll": "Cổ thư (tông sepia, dấu son)",
    "history-imperial": "Hoàng triều (đỏ son, vàng kim)",
    "history-archive": "Tư liệu (đen trắng, khung phim)",
}

# ffmpeg filters appended to every scene; each ends with "," because it is spliced into a filter chain.
HISTORY_GRADES = {
    "history-scroll": "hue=s=0.45,colorbalance=rs=.10:gs=.03:bs=-.10:rm=.06:bm=-.06,",
    "history-imperial": "colorbalance=rs=.06:gs=.01:bs=-.05,eq=contrast=1.05:saturation=1.08,",
    "history-archive": "hue=s=0,colorbalance=rs=.08:gs=.03:bs=-.06,vignette=PI/5,noise=alls=8:allf=t,",
}

# xfade transitions cycled through a video's cuts when the transition choice is "template".
HISTORY_TRANSITIONS = {
    "history-scroll": ("dissolve", "fadeblack"),
    "history-imperial": ("smoothleft", "fade"),
    "history-archive": ("fadeblack", "hblur"),
}

_SERIF_FILES =("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf")
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
    """Cổ thư: the picture stays visible and fades to dark brown; the year sits in a square red seal (Asian
    chop style) and the cream title between two bronze rules. Replaced a parchment box with wooden rollers."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPen

    fade = QLinearGradient(0, height * 0.38, 0, height)
    fade.setColorAt(0, QColor(28, 16, 8, 0))
    fade.setColorAt(0.45, QColor(28, 16, 8, 170))
    fade.setColorAt(1, QColor(20, 11, 5, 240))
    painter.fillRect(QRectF(0, height * 0.38, width, height * 0.62), fade)
    bronze = QColor("#e2c48f")
    top = height * 0.585
    if badge:
        side = 150 * s
        seal = QRectF(width / 2 - side / 2, top - side - 30 * s, side, side)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(168, 32, 26, 235))
        painter.drawRoundedRect(seal, 10 * s, 10 * s)
        painter.setPen(QPen(QColor(250, 232, 200, 220), 3 * s))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(seal.adjusted(10 * s, 10 * s, -10 * s, -10 * s), 6 * s, 6 * s)
        painter.setPen(QColor("#fbe9cf"))
        painter.setFont(_font(46 * s, True, 1 * s))
        painter.drawText(seal, Qt.AlignCenter, badge)
    painter.setPen(bronze)
    painter.setFont(_font(27 * s, True, 6 * s))
    painter.drawText(QRectF(0, top, width, 40 * s), Qt.AlignCenter, label)
    painter.setPen(QPen(QColor("#c9a46a"), 2 * s))
    painter.drawLine(QPointF(width * 0.18, top + 58 * s), QPointF(width * 0.82, top + 58 * s))
    text = QRectF(width * 0.09, top + 80 * s, width * 0.82, height * 0.25)
    flags = Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap
    painter.setPen(QColor("#f6ead2"))
    _fit_text(painter, title, text, 70 * s, 36 * s, True, flags)
    below = painter.boundingRect(text, flags, title).bottom() + 28 * s
    painter.setPen(QPen(QColor("#c9a46a"), 2 * s))
    painter.drawLine(QPointF(width * 0.18, below), QPointF(width * 0.82, below))


def _imperial(painter, width, height, s, title, badge, label):
    """Hoàng triều: the picture fades to deep lacquer red; a large gold-outlined year, a thin gold divider with a
    diamond and a pale gold title. Replaced a solid red box with double gold borders."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFontMetricsF, QLinearGradient, QPainterPath, QPen, QPolygonF

    fade = QLinearGradient(0, height * 0.36, 0, height)
    fade.setColorAt(0, QColor(40, 4, 6, 0))
    fade.setColorAt(0.45, QColor(52, 6, 9, 185))
    fade.setColorAt(1, QColor(26, 3, 5, 245))
    painter.fillRect(QRectF(0, height * 0.36, width, height * 0.64), fade)
    gold = QColor("#d9ad4a")
    y = height * 0.555
    painter.setPen(QColor("#f0c96a"))
    painter.setFont(_font(27 * s, True, 6 * s))
    painter.drawText(QRectF(0, y, width, 40 * s), Qt.AlignCenter, label)
    y += 52 * s
    if badge:
        font = _font(170 * s, True, 4 * s)
        metrics = QFontMetricsF(font)
        path = QPainterPath()
        path.addText(QPointF(width / 2 - metrics.horizontalAdvance(badge) / 2, y + metrics.ascent()), font, badge)
        painter.setBrush(QColor(217, 173, 74, 60))
        painter.setPen(QPen(gold, 3 * s))
        painter.drawPath(path)
        y += metrics.height() + 6 * s
    centre, diamond = width / 2, 11 * s
    painter.setPen(QPen(gold, 2 * s))
    painter.drawLine(QPointF(width * 0.2, y), QPointF(centre - 26 * s, y))
    painter.drawLine(QPointF(centre + 26 * s, y), QPointF(width * 0.8, y))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gold)
    painter.drawPolygon(QPolygonF([QPointF(centre, y - diamond), QPointF(centre + diamond, y),
                                   QPointF(centre, y + diamond), QPointF(centre - diamond, y)]))
    painter.setPen(QColor("#f7e3a6"))
    _fit_text(painter, title, QRectF(width * 0.09, y + 34 * s, width * 0.82, height * 0.93 - (y + 34 * s)),
              66 * s, 34 * s, True, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap)


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
