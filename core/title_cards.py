"""History title cards drawn with Qt (full-frame transparent PNG overlaid while the hook is read).

Qt shapes Vietnamese text correctly and allows richer layouts than ffmpeg drawtext.
"""
import os
from pathlib import Path

HISTORY_TEMPLATES = {
    "history-scroll": "Cổ thư (tông sepia, dấu son)",
    "history-imperial": "Hoàng triều (đỏ son, vàng kim)",
    "history-archive": "Tư liệu (đen trắng, khung phim)",
    "history-inkwash": "Thủy mặc (giấy ngà, mực tàu)",
    "history-battle": "Chiến sử (xanh rêu, bản đồ tác chiến)",
    "history-modern": "Hiện đại (phẳng, màu nổi)",
}

# ffmpeg filters appended to every scene; each ends with "," because it is spliced into a filter chain.
HISTORY_GRADES = {
    "history-scroll": "hue=s=0.45,colorbalance=rs=.10:gs=.03:bs=-.10:rm=.06:bm=-.06,",
    "history-imperial": "colorbalance=rs=.06:gs=.01:bs=-.05,eq=contrast=1.05:saturation=1.08,",
    "history-archive": "hue=s=0,colorbalance=rs=.08:gs=.03:bs=-.06,vignette=PI/5,noise=alls=8:allf=t,",
    "history-inkwash": "hue=s=0.25,colorbalance=rs=-.02:gs=.01:bs=.05,eq=brightness=.03:contrast=.94,",
    "history-battle": "colorbalance=rs=.02:gs=.05:bs=-.08,eq=contrast=1.08:saturation=0.8,vignette=PI/6,",
    "history-modern": "eq=contrast=1.06:saturation=1.15,",
}

# xfade transitions cycled through a video's cuts when the transition choice is "template".
HISTORY_TRANSITIONS = {
    "history-scroll": ("dissolve", "fadeblack"),
    "history-imperial": ("smoothleft", "fade"),
    "history-archive": ("fadeblack", "hblur"),
    "history-inkwash": ("dissolve", "fade"),
    "history-battle": ("smoothleft", "fadeblack"),
    "history-modern": ("slideup", "wipeleft"),
}

_SERIF_FILES =("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf")
_SANS_FILES = ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf")
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


def _sans_family() -> str:
    """Segoe UI loaded from its files: the offscreen Qt platform only sees fonts added this way."""
    from PySide6.QtGui import QFontDatabase

    _serif_family()
    if "sans" not in _families:
        family = "Segoe UI"
        for path in _SANS_FILES:
            if Path(path).is_file():
                loaded = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(path))
                family = loaded[0] if loaded else family
        _families["sans"] = family
    return _families["sans"]


def _font(size_px: float, bold: bool = False, spacing: float = 0.0, family: str = ""):
    from PySide6.QtGui import QFont

    font = QFont(family or _serif_family())
    font.setPixelSize(max(8, round(size_px)))
    font.setBold(bold)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return font


def _fit_text(painter, text: str, rect, max_px: float, min_px: float, bold: bool, flags, family: str = "") -> None:
    """Draw wrapped text at the largest size (max_px..min_px) that fits inside rect."""
    size = max_px
    while size > min_px:
        painter.setFont(_font(size, bold, family=family))
        if painter.boundingRect(rect, flags, text).height() <= rect.height():
            break
        size -= 2
    painter.setFont(_font(size, bold, family=family))
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


def _inkwash(painter, width, height, s, title, badge, label):
    """Thủy mặc: the picture dissolves into ivory rice paper; a dark ink year over a tapered brush stroke, a small
    red seal holding the label and an ink title."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPainterPath, QPen

    fade = QLinearGradient(0, height * 0.40, 0, height)
    fade.setColorAt(0, QColor(244, 238, 224, 0))
    fade.setColorAt(0.35, QColor(244, 238, 224, 215))
    fade.setColorAt(1, QColor(240, 233, 216, 250))
    painter.fillRect(QRectF(0, height * 0.40, width, height * 0.60), fade)
    ink, left = QColor("#1f2a2e"), width * 0.09
    y = height * 0.57
    if badge:
        stroke = QPainterPath(QPointF(left - 10 * s, y + 150 * s))
        stroke.cubicTo(QPointF(width * 0.35, y + 118 * s), QPointF(width * 0.55, y + 128 * s),
                       QPointF(width * 0.70, y + 140 * s))
        stroke.cubicTo(QPointF(width * 0.55, y + 150 * s), QPointF(width * 0.30, y + 160 * s),
                       QPointF(left - 10 * s, y + 150 * s))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(31, 42, 46, 70))
        painter.drawPath(stroke)
        painter.setPen(ink)
        painter.setFont(_font(150 * s, True))
        painter.drawText(QRectF(left, y, width * 0.84, 170 * s), Qt.AlignLeft | Qt.AlignVCenter, badge)
    words = label.split()
    seal = QRectF(width * 0.91 - 92 * s, y + 10 * s, 92 * s, 50 * s * max(2, len(words)) + 24 * s)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(178, 38, 30, 230))
    painter.drawRoundedRect(seal, 8 * s, 8 * s)
    painter.setPen(QColor("#fbeee0"))
    painter.setFont(_font(26 * s, True))
    painter.drawText(seal.adjusted(2 * s, 8 * s, -2 * s, -8 * s), Qt.AlignCenter, "\n".join(words))
    y += 190 * s
    painter.setPen(QPen(QColor(31, 42, 46, 150), 2 * s))
    painter.drawLine(QPointF(left, y), QPointF(left + 120 * s, y))
    painter.setPen(ink)
    _fit_text(painter, title, QRectF(left, y + 26 * s, width * 0.72, height * 0.94 - (y + 26 * s)),
              66 * s, 32 * s, True, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)


def _battle(painter, width, height, s, title, badge, label):
    """Chiến sử: the picture fades to dark olive under a faint map grid; the year sits in khaki target brackets
    next to a red advance arrow, the title in pale khaki."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPainterPath, QPen, QPolygonF

    top = height * 0.40
    fade = QLinearGradient(0, top, 0, height)
    fade.setColorAt(0, QColor(22, 28, 16, 0))
    fade.setColorAt(0.4, QColor(24, 30, 18, 200))
    fade.setColorAt(1, QColor(16, 20, 12, 245))
    painter.fillRect(QRectF(0, top, width, height - top), fade)
    painter.setPen(QPen(QColor(196, 186, 140, 38), 1.5 * s))
    step = 90 * s
    x = 0.0
    while x < width:
        painter.drawLine(QPointF(x, height * 0.52), QPointF(x, height))
        x += step
    row = height * 0.52
    while row < height:
        painter.drawLine(QPointF(0, row), QPointF(width, row))
        row += step
    khaki, left = QColor("#d6c89a"), width * 0.09
    y = height * 0.56
    painter.setPen(khaki)
    painter.setFont(_font(26 * s, True, 8 * s))
    painter.drawText(QRectF(left, y, width * 0.84, 40 * s), Qt.AlignLeft | Qt.AlignVCenter, label)
    y += 64 * s
    if badge:
        painter.setFont(_font(130 * s, True, 2 * s))
        box = painter.boundingRect(QRectF(left + 24 * s, y, width, 160 * s), Qt.AlignLeft | Qt.AlignVCenter, badge)
        box = box.adjusted(-24 * s, -6 * s, 24 * s, 6 * s)
        corner = 34 * s
        painter.setPen(QPen(khaki, 5 * s))
        for cx, cy, dx, dy in ((box.left(), box.top(), 1, 1), (box.right(), box.top(), -1, 1),
                               (box.left(), box.bottom(), 1, -1), (box.right(), box.bottom(), -1, -1)):
            painter.drawLine(QPointF(cx, cy), QPointF(cx + dx * corner, cy))
            painter.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy * corner))
        painter.setPen(QColor("#f1ead0"))
        painter.drawText(box, Qt.AlignCenter, badge)
        arrow_y = box.center().y()
        start, end = box.right() + 30 * s, width * 0.91
        if end - start > 80 * s:
            path = QPainterPath(QPointF(start, arrow_y + 30 * s))
            path.quadTo(QPointF((start + end) / 2, arrow_y - 40 * s), QPointF(end - 30 * s, arrow_y))
            painter.setPen(QPen(QColor(196, 44, 36, 230), 7 * s, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(196, 44, 36, 240))
            painter.drawPolygon(QPolygonF([QPointF(end, arrow_y), QPointF(end - 40 * s, arrow_y - 22 * s),
                                           QPointF(end - 34 * s, arrow_y + 20 * s)]))
        y = box.bottom() + 30 * s
    painter.setPen(QColor("#ece3c4"))
    _fit_text(painter, title, QRectF(left, y, width * 0.84, height * 0.93 - y),
              64 * s, 30 * s, True, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)


def _modern(painter, width, height, s, title, badge, label):
    """Hiện đại: flat and bright for short social videos; a navy panel at the bottom, an orange year chip, a label
    pill and a white sans-serif title."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor

    sans = _sans_family()
    panel = QRectF(0, height * 0.60, width, height * 0.40)
    painter.fillRect(panel, QColor(16, 24, 48, 228))
    painter.fillRect(QRectF(0, panel.top(), width, 10 * s), QColor("#ff5a36"))
    left = width * 0.08
    painter.setFont(_font(24 * s, True, 3 * s, sans))
    text = painter.boundingRect(QRectF(0, 0, width, 50 * s), Qt.AlignLeft | Qt.AlignVCenter, label)
    pill = QRectF(left, panel.top() + 48 * s, text.width() + 44 * s, text.height() + 18 * s)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 36))
    painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
    painter.setPen(QColor("#ffd7cc"))
    painter.drawText(pill, Qt.AlignCenter, label)
    if badge:
        painter.setFont(_font(64 * s, True, 1 * s, sans))
        size = painter.boundingRect(QRectF(0, 0, width, 100 * s), Qt.AlignLeft | Qt.AlignVCenter, badge)
        chip = QRectF(width * 0.92 - size.width() - 48 * s, panel.top() - 60 * s, size.width() + 48 * s, 104 * s)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ff5a36"))
        painter.drawRoundedRect(chip, 18 * s, 18 * s)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(chip, Qt.AlignCenter, badge)
    y = pill.bottom() + 30 * s
    painter.setPen(QColor("#ffffff"))
    _fit_text(painter, title, QRectF(left, y, width * 0.84, height * 0.95 - y),
              68 * s, 32 * s, True, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, sans)


_DRAWERS = {"history-scroll": _scroll, "history-imperial": _imperial, "history-archive": _archive,
            "history-inkwash": _inkwash, "history-battle": _battle, "history-modern": _modern}


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
