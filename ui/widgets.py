"""Reusable widgets for the card-based layout: section cards, the step bar, card pickers and the render progress panel."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ui import icons

ACCENT = "#2563eb"
MUTED = "#64748b"


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property used in a selector changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    for child in widget.findChildren(QWidget):
        child.style().unpolish(child)
        child.style().polish(child)


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


class Card(QFrame):
    """White rounded section with an icon badge, a title, a subtitle and header actions on the right."""

    def __init__(self, title: str, subtitle: str = "", icon: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 20)
        outer.setSpacing(14)
        header = QHBoxLayout()
        header.setSpacing(12)
        if icon:
            badge = label("", "badge")
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(30, 30)
            badge.setPixmap(icons.pixmap(icon, "#ffffff", 16, 2))
            header.addWidget(badge, 0, Qt.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = label(title, "cardTitle")
        titles.addWidget(self.title)
        if subtitle:
            self.subtitle = label(subtitle, "cardSubtitle", wrap=True)
            titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        header.addLayout(self.actions)
        outer.addLayout(header)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        outer.addLayout(self.body)


class _StepItem(QFrame):
    def __init__(self, stepper: "Stepper", index: int, title: str, subtitle: str):
        super().__init__()
        self._stepper, self._index = stepper, index
        self.setObjectName("stepItem")
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(10)
        self.circle = label(str(index + 1), "stepCircle")
        self.circle.setAlignment(Qt.AlignCenter)
        self.circle.setFixedSize(28, 28)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.title = label(title, "stepTitle")
        self.subtitle = label(subtitle, "stepSubtitle")
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        row.addWidget(self.circle)
        row.addLayout(texts)

    def set_state(self, state: str) -> None:
        for widget in (self, self.circle, self.title):
            widget.setProperty("state", state)
        self.circle.setText("✓" if state == "done" else str(self._index + 1))
        self.setCursor(Qt.ForbiddenCursor if state == "todo" else Qt.PointingHandCursor)
        repolish(self)

    def mousePressEvent(self, event):
        if self.property("state") != "todo":
            self._stepper.clicked.emit(self._index)
        super().mousePressEvent(event)


class Stepper(QWidget):
    """Horizontal step bar; steps up to `reached` can be clicked to go back."""

    clicked = Signal(int)

    def __init__(self, steps: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._items = []
        for index, (title, subtitle) in enumerate(steps):
            if index:
                line = QFrame()
                line.setObjectName("stepLine")
                line.setFixedHeight(2)
                line.setMinimumWidth(16)
                row.addWidget(line, 1, Qt.AlignVCenter)
            item = _StepItem(self, index, title, subtitle)
            self._items.append(item)
            row.addWidget(item)

    def set_state(self, current: int, reached: int) -> None:
        for index, item in enumerate(self._items):
            item.set_state("current" if index == current else "done" if index <= reached else "todo")

    def set_title(self, index: int, title: str, subtitle: str) -> None:
        self._items[index].title.setText(title)
        self._items[index].subtitle.setText(subtitle)


class _Choice(QFrame):
    def __init__(self, owner: "ChoiceCards", index: int, title: str, subtitle: str, icon_name: str | None,
                 badge: str, tile: bool, art_size: QSize | None, indicator: bool):
        super().__init__()
        self._owner, self._index = owner, index
        self.setObjectName("choice")
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("selected", False)
        self.indicator = None
        self.art = None
        self.title = label(title, "choiceTitle", wrap=True)
        self.subtitle = label(subtitle, "choiceSubtitle", wrap=True) if subtitle else None
        if tile:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(10, 10, 10, 12)
            layout.setSpacing(6)
            self.art = label("", "choiceArt")
            self.art.setAlignment(Qt.AlignCenter)
            if art_size:
                self.art.setFixedHeight(art_size.height())
            if icon_name:
                self.art.setPixmap(icons.pixmap(icon_name, ACCENT, 40, 1.5))
            layout.addWidget(self.art)
        else:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setSpacing(10)
            if indicator:
                self.indicator = QLabel()
                layout.addWidget(self.indicator, 0, Qt.AlignTop)
            elif icon_name:
                mark = label("", "choiceIcon")
                mark.setFixedSize(32, 32)
                mark.setAlignment(Qt.AlignCenter)
                mark.setPixmap(icons.pixmap(icon_name, ACCENT, 18))
                layout.addWidget(mark, 0, Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        heading = QHBoxLayout()
        heading.setSpacing(6)
        heading.addWidget(self.title, 1)
        if badge:
            heading.addWidget(label(badge, "choiceBadge"), 0, Qt.AlignTop)
        texts.addLayout(heading)
        if self.subtitle:
            texts.addWidget(self.subtitle)
        if tile:
            texts.addStretch(1)
        layout.addLayout(texts, 1)
        self._update_indicator()

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self._update_indicator()
        repolish(self)

    def _update_indicator(self) -> None:
        if self.indicator is not None:
            selected = bool(self.property("selected"))
            self.indicator.setPixmap(icons.pixmap("box-checked" if selected else "box",
                                                  ACCENT if selected else "#94a3b8", 20))

    def mousePressEvent(self, event):
        if self.isEnabled():
            self._owner.setCurrentIndex(self._index)
        super().mousePressEvent(event)


class ChoiceCards(QWidget):
    """A grid of selectable cards with the QComboBox calls the window uses (currentData, findData, ...)."""

    currentIndexChanged = Signal(int)

    def __init__(self, columns: int = 4, tile: bool = False, art_size: QSize | None = None,
                 indicator: bool = False, parent=None):
        super().__init__(parent)
        self._columns, self._tile, self._art_size, self._indicator = columns, tile, art_size, indicator
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(12)
        for column in range(columns):
            self._grid.setColumnStretch(column, 1)
        self._items: list[_Choice] = []
        self._data: list = []
        self._current = -1

    def clear(self) -> None:
        for item in self._items:
            item.deleteLater()
        self._items, self._data = [], []
        changed = self._current != -1
        self._current = -1
        if changed:
            self.currentIndexChanged.emit(-1)

    def addItem(self, title: str, data=None, subtitle: str = "", icon: str | None = None,
                badge: str = "", enabled: bool = True) -> int:
        index = len(self._items)
        item = _Choice(self, index, title, subtitle, icon, badge, self._tile, self._art_size, self._indicator)
        item.setEnabled(enabled)
        item.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._grid.addWidget(item, index // self._columns, index % self._columns)
        self._items.append(item)
        self._data.append(data)
        if self._current == -1 and enabled and not self._indicator:
            self.setCurrentIndex(index)
        return index

    def setItemPixmap(self, index: int, image: QPixmap) -> None:
        art = self._items[index].art
        if art is not None and not image.isNull():
            art.setPixmap(image.scaledToHeight(art.height() - 8, Qt.SmoothTransformation))

    def count(self) -> int:
        return len(self._items)

    def currentIndex(self) -> int:
        return self._current

    def setCurrentIndex(self, index: int) -> None:
        if index == self._current or not -1 <= index < len(self._items):
            return
        self._current = index
        for position, item in enumerate(self._items):
            item.set_selected(position == index)
        self.currentIndexChanged.emit(index)

    def currentData(self):
        return self._data[self._current] if self._current >= 0 else None

    def currentText(self) -> str:
        return self._items[self._current].title.text() if self._current >= 0 else ""

    def itemData(self, index: int):
        return self._data[index]

    def itemText(self, index: int) -> str:
        return self._items[index].title.text()

    def findData(self, data) -> int:
        return self._data.index(data) if data in self._data else -1


# Pipeline stages grouped into the four steps shown while rendering.
RENDER_GROUPS = (
    ("Chuẩn bị kịch bản & ảnh", ("prepare_clips", "prepare_content", "prepare_assets")),
    ("Giọng đọc & phụ đề", ("generate_tts", "generate_subtitle")),
    ("Dựng hình & hiệu ứng", ("build_timeline", "template_composition", "ffmpeg_render")),
    ("Kiểm tra & hoàn tất", ("validate",)),
)


class _RenderStage(QFrame):
    def __init__(self, number: int, name: str):
        super().__init__()
        self.setObjectName("renderStage")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        self.mark = label(str(number), "renderMark")
        self.mark.setAlignment(Qt.AlignCenter)
        self.mark.setFixedSize(24, 24)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(label(f"{number}. {name}", "renderStageName", wrap=True))
        self.state = label("Đang chờ", "renderStageState")
        texts.addWidget(self.state)
        row.addWidget(self.mark, 0, Qt.AlignTop)
        row.addLayout(texts, 1)
        self._number = number

    def set_state(self, state: str) -> None:
        self.setProperty("state", state)
        self.mark.setProperty("state", state)
        self.mark.setText("✓" if state == "done" else "!" if state == "failed" else str(self._number))
        self.state.setText({"todo": "Đang chờ", "active": "Đang chạy...", "done": "Hoàn thành",
                            "failed": "Lỗi"}[state])
        repolish(self)


class RenderProgress(QFrame):
    """Dark panel with overall percent, a cancel button and the four render steps."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("renderPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(14)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = label("Đang tạo video", "renderTitle")
        self.detail = label("", "renderDetail", wrap=True)
        titles.addWidget(self.title)
        titles.addWidget(self.detail)
        self.percent = label("0%", "renderPercent")
        self.cancel = QPushButton("Hủy")
        self.cancel.setObjectName("darkButton")
        self.cancel.setCursor(Qt.PointingHandCursor)
        self.cancel.clicked.connect(self._on_cancel)
        header.addLayout(titles, 1)
        header.addWidget(self.percent, 0, Qt.AlignVCenter)
        header.addSpacing(12)
        header.addWidget(self.cancel, 0, Qt.AlignVCenter)
        layout.addLayout(header)
        self.bar = QProgressBar()
        self.bar.setObjectName("renderBar")
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        layout.addWidget(self.bar)
        stages = QHBoxLayout()
        stages.setSpacing(10)
        self._stages = [_RenderStage(number, name) for number, (name, _keys) in enumerate(RENDER_GROUPS, 1)]
        for stage in self._stages:
            stages.addWidget(stage, 1)
        layout.addLayout(stages)
        self._active = 0

    def _on_cancel(self) -> None:
        self.cancel.setEnabled(False)
        self.title.setText("Đang hủy...")
        self.detail.setText("Dừng ngay nếu đang dựng hình; nếu đang tạo giọng đọc thì dừng khi bước đó xong.")
        self.cancel_requested.emit()

    def start(self) -> None:
        self._active = 0
        self.cancel.setVisible(True)
        self.cancel.setEnabled(True)
        self.title.setText("Đang tạo video")
        self.detail.setText("Có thể mất vài phút; đừng đóng ứng dụng.")
        self._set(0)
        for index, stage in enumerate(self._stages):
            stage.set_state("active" if index == 0 else "todo")

    def update_stage(self, stage: str, percent: int, text: str) -> None:
        group = next((index for index, (_name, keys) in enumerate(RENDER_GROUPS) if stage in keys), None)
        if group is not None and group != self._active:
            self._active = group
            for index, item in enumerate(self._stages):
                item.set_state("done" if index < group else "active" if index == group else "todo")
        self.detail.setText(text)
        if percent >= 0:
            self._set(percent)

    def finish(self, ok: bool, text: str, title: str = "") -> None:
        self.cancel.setVisible(False)
        self.title.setText(title or ("Video đã hoàn thành" if ok else "Không tạo được video"))
        self.detail.setText(text)
        if ok:
            self._set(100)
            for stage in self._stages:
                stage.set_state("done")
        else:
            self._stages[self._active].set_state("failed")

    def _set(self, percent: int) -> None:
        self.bar.setValue(percent)
        self.percent.setText(f"{percent}%")
