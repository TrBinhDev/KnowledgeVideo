"""Saved videos: every run folder in the output directory, newest first, with a way to reopen it."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core import catalog
from core.config import list_runs, output_directory
from core.preview import scene_picture
from ui import icons
from ui.widgets import Card, label

STEP_OF_RUN = (
    ("video", "Đã có video"),
    ("scenes", "Đang ở bước Cảnh & ảnh"),
    ("script", "Đang ở bước Kịch bản"),
    ("outline", "Đang ở bước Đề cương"),
    ("topics", "Đang ở bước Chủ đề"),
)


def run_status(state: dict) -> str:
    return next((text for key, text in STEP_OF_RUN if state.get(key)), "Mới bắt đầu")


def _created(directory: Path) -> str:
    try:
        return datetime.strptime(directory.name[:15], "%Y%m%d_%H%M%S").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return datetime.fromtimestamp(directory.stat().st_mtime).strftime("%d/%m/%Y %H:%M")


def _cover(directory: Path, state: dict) -> Path | None:
    thumbnail = directory / "render" / "thumbnail.jpg"
    if thumbnail.is_file():
        return thumbnail
    for scene in state.get("scenes") or []:
        path = scene_picture(directory, scene)
        if path and path.is_file():
            return path
    return None


def _open_path(path: Path) -> None:
    if path.exists():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class _RunRow(QFrame):
    def __init__(self, page: "HistoryPage", directory: Path, state: dict):
        super().__init__()
        self.setObjectName("choice")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(14)
        cover = QLabel()
        cover.setObjectName("choiceArt")
        cover.setFixedSize(58, 100)
        cover.setAlignment(Qt.AlignCenter)
        cover_path = _cover(directory, state)
        if cover_path:
            cover.setPixmap(QPixmap(str(cover_path)).scaled(58, 100, Qt.KeepAspectRatioByExpanding,
                                                            Qt.SmoothTransformation).copy(0, 0, 58, 100))
        else:
            cover.setPixmap(icons.pixmap("film", "#94a3b8", 24))
        row.addWidget(cover)

        script = state.get("script") or {}
        title = script.get("title") or state.get("topic") or state.get("input") or directory.name
        seconds = (script.get("timing") or {}).get("seconds")
        length = f"{seconds:.0f} giây" if seconds else f"mục tiêu {state.get('duration', '?')} giây"
        template = catalog.TEMPLATES_BY_TYPE.get(state.get("content_type"), {}).get((state.get("render") or {}).get("template"), "")
        kind = "Video clip" if state.get("kind") == "clip" else "Video ảnh"
        meta = " · ".join(part for part in (kind, _created(directory), length, f"{len(state.get('scenes') or [])} cảnh",
                                            template.partition(" (")[0]) if part)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        texts.addWidget(label(title, "choiceTitle", wrap=True))
        texts.addWidget(label(meta, "choiceSubtitle", wrap=True))
        video = Path(state["video"]) if state.get("video") else None
        has_video = bool(video and video.is_file())
        # A recorded video that was deleted from disk counts as not rendered.
        status_text = run_status(state if has_video else {key: value for key, value in state.items() if key != "video"})
        status = label(status_text, "okTag" if has_video else "choiceBadge")
        texts.addWidget(status, 0, Qt.AlignLeft)
        texts.addStretch(1)
        row.addLayout(texts, 1)

        buttons = QVBoxLayout()
        buttons.setSpacing(6)
        reopen = QPushButton("Mở để sửa")
        reopen.setObjectName("soft")
        reopen.clicked.connect(lambda: page.open_requested.emit(str(directory)))
        folder = QPushButton("Thư mục")
        folder.clicked.connect(lambda: _open_path(directory))
        buttons.addWidget(reopen)
        buttons.addWidget(folder)
        if has_video:
            watch = QPushButton("Xem video")
            watch.clicked.connect(lambda: _open_path(video))
            buttons.addWidget(watch)
        buttons.addStretch(1)
        row.addLayout(buttons)


class HistoryPage(QWidget):
    """List of saved runs; `open_requested(path)` asks the window to load one."""

    open_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.card = Card("Lịch sử video", "Các video đã làm, mới nhất trước. Mở lại để sửa ảnh, đổi mẫu hoặc render lại.",
                         "clock")
        refresh = QPushButton("Làm mới")
        refresh.setObjectName("soft")
        refresh.setIcon(icons.icon("refresh", "#1d4ed8", 16))
        refresh.clicked.connect(self.refresh)
        self.card.actions.addWidget(refresh)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(10)
        self.card.body.addLayout(self.rows)
        self.empty = label("", "hint", wrap=True)
        self.card.body.addWidget(self.empty)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.card)
        layout.addStretch(1)

    def refresh(self) -> None:
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        runs = list_runs()
        for directory, state in runs:
            self.rows.addWidget(_RunRow(self, directory, state))
        self.empty.setText("" if runs else f"Chưa có video nào trong {output_directory()}.")
