"""Template gallery: every template with its thumbnail and a moving preview of its transitions."""
from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from core import catalog
from core.preview import gallery_source, render_preview, render_thumbnail
from ui import icons
from ui.widgets import Card, ChoiceCards, label
from ui.worker import TaskThread


class TemplatesPage(QWidget):
    """`use_requested(template, transition)` hands the chosen look to the video being made."""

    use_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        card = Card("Mẫu video", "Xem trước từng mẫu với chuyển cảnh và chuyển động như video thật "
                    "(không có phụ đề, giọng đọc).", "layout")
        self.templates = ChoiceCards(columns=3, tile=True, art_size=QSize(0, 230))
        for key, name in catalog.TEMPLATES_BY_TYPE["kien_thuc"].items():
            title, _, style = name.partition(" (")
            self.templates.addItem(title, key, style.rstrip(")"))
        self.transition = QComboBox()
        for key, name in catalog.TRANSITIONS.items():
            self.transition.addItem(name, key)
        self.motion = QCheckBox("Chuyển động Ken Burns (zoom, lia chậm)")
        self.motion.setChecked(True)
        options = QHBoxLayout()
        options.addWidget(label("Chuyển cảnh", "fieldLabel"))
        options.addWidget(self.transition, 1)
        options.addSpacing(12)
        options.addWidget(self.motion)
        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(self.templates)
        left.addLayout(options)
        left.addStretch(1)

        self.video = QVideoWidget()
        self.video.setFixedSize(270, 480)
        self.player = QMediaPlayer(self)
        self.player.setVideoOutput(self.video)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.hint = label("", "hint", wrap=True)
        use = QPushButton("Dùng mẫu này")
        use.setObjectName("primary")
        use.setIcon(icons.icon("check", "#ffffff", 16))
        use.clicked.connect(lambda: self.use_requested.emit(self.templates.currentData(), self.transition.currentData()))
        side = QVBoxLayout()
        side.setSpacing(10)
        side.addWidget(label("Xem trước", "fieldLabel"))
        side.addWidget(self.video, 0, Qt.AlignHCenter)
        side.addWidget(self.hint)
        side.addWidget(use)
        side.addStretch(1)
        side_panel = QWidget()
        side_panel.setFixedWidth(300)
        side_panel.setLayout(side)
        body = QHBoxLayout()
        body.setSpacing(20)
        body.addLayout(left, 1)
        body.addWidget(side_panel)
        card.body.addLayout(body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card)
        layout.addStretch(1)

        self.source = None
        self.running = False
        self.pending = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._update_preview)
        for widget in (self.templates, self.transition):
            widget.currentIndexChanged.connect(lambda _index: self.timer.start())
        self.motion.toggled.connect(lambda _checked: self.timer.start())

    def activate(self) -> None:
        """Pick the pictures (newest video, else drawn samples), then thumbnails, then the preview."""
        if self.running:
            return
        self.running = True
        self.hint.setText("Đang chuẩn bị ảnh mẫu...")
        templates = [self.templates.itemData(index) for index in range(self.templates.count())]

        def job(_progress):
            source = gallery_source()
            return source, {template: str(render_thumbnail(source, template)) for template in templates}

        self._task = TaskThread(job, self)
        self._task.succeeded.connect(self._on_source)
        self._task.failed.connect(self._on_failed)
        self._task.start()

    def deactivate(self) -> None:
        self.player.pause()

    def _on_source(self, result) -> None:
        self.source, thumbnails = result
        for template, path in thumbnails.items():
            self.templates.setItemPixmap(self.templates.findData(template), QPixmap(path))
        self.running = False
        self._update_preview()

    def _on_failed(self, message: str) -> None:
        self.running = False
        self.pending = False
        self.hint.setText(f"Không tạo được xem trước: {message}")

    def _update_preview(self) -> None:
        if self.source is None:
            return
        if self.running:
            self.pending = True
            return
        self.running = True
        source, template = self.source, self.templates.currentData()
        transition, motion = self.transition.currentData(), self.motion.isChecked()
        self.hint.setText(f"Đang tạo xem trước {self.templates.currentText()}"
                          f"{' có chuyển động' if motion else ''}...")
        self._task = TaskThread(lambda _p: str(render_preview(source, template, transition, motion)), self)
        self._task.succeeded.connect(self._on_preview)
        self._task.failed.connect(self._on_failed)
        self._task.start()

    def _on_preview(self, path: str) -> None:
        self.running = False
        if self.pending:
            self.pending = False
            self._update_preview()
            return
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self.hint.setText(f"{self.templates.currentText()} · {self.transition.currentText()}. "
                          f"Dùng {self.source.origin}.")
