"""Settings stored in .env: AI access, output folder, Wikimedia User-Agent and video font."""
import os
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core.config import output_directory, update_env
from ui import icons
from ui.widgets import Card, label

# (env key, label, hint); the API key field is masked.
AI_FIELDS = (
    ("KV_GEMINI_API_KEY", "Gemini API key", "Lấy ở Google AI Studio. Lưu trong file .env trên máy này."),
    ("KV_GEMINI_MODEL", "Gemini model mặc định", "Ví dụ gemini-3.8-flash. Trong app vẫn chọn được model khác."),
    ("KV_GEMINI_IMAGE_MODEL", "Gemini model tạo ảnh", "Chỉ dùng cho nút \"Ảnh AI (Gemini)\"; cần key có billing."),
    ("KV_OLLAMA_URL", "Ollama URL", "Mặc định http://127.0.0.1:11434"),
    ("KV_OLLAMA_MODEL", "Ollama model mặc định", "Ví dụ gemma3"),
    ("KV_OLLAMA_TIMEOUT_SECONDS", "Ollama timeout (giây)", "Model chạy trên máy có thể chậm; mặc định 240."),
)
OTHER_FIELDS = (
    ("KV_OUTPUT_DIR", "Thư mục lưu video", "Để trống: thư mục output trong project."),
    ("KV_HTTP_USER_AGENT", "User-Agent khi gọi Wikimedia", "Nên thêm thông tin liên hệ của bạn theo chính sách Wikimedia."),
    ("KV_VIDEO_FONT", "Font chữ trên video (.ttf)", "Để trống: Arial. Cần font có đủ dấu tiếng Việt."),
)


class SettingsPage(QWidget):
    saved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields: dict[str, QLineEdit] = {}
        ai = Card("AI viết nội dung", "Thay đổi có hiệu lực ngay, không cần mở lại ứng dụng.", "sparkles")
        ai.body.addLayout(self._grid(AI_FIELDS))
        show = QPushButton("Hiện key")
        show.setCheckable(True)
        show.toggled.connect(self._toggle_key)
        self.show_key = show
        ai.actions.addWidget(show)
        other = Card("Lưu trữ & video", "", "sliders")
        other.body.addLayout(self._grid(OTHER_FIELDS))
        self.fields["KV_GEMINI_API_KEY"].setEchoMode(QLineEdit.Password)
        save = QPushButton("Lưu cài đặt")
        save.setObjectName("primary")
        save.setIcon(icons.icon("check", "#ffffff", 16))
        save.clicked.connect(self._save)
        reload = QPushButton("Hoàn tác")
        reload.clicked.connect(self.load)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(reload)
        buttons.addWidget(save)
        other.body.addLayout(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(ai)
        layout.addWidget(other)
        layout.addStretch(1)

    def _grid(self, fields) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        for index, (key, name, hint) in enumerate(fields):
            row = index * 3
            edit = QLineEdit()
            self.fields[key] = edit
            grid.addWidget(label(name, "fieldLabel"), row, 0)
            if key in ("KV_OUTPUT_DIR", "KV_VIDEO_FONT"):
                browse = QPushButton("Chọn...")
                browse.clicked.connect(lambda _checked=False, k=key: self._browse(k))
                line = QHBoxLayout()
                line.addWidget(edit, 1)
                line.addWidget(browse)
                grid.addLayout(line, row + 1, 0)
            else:
                grid.addWidget(edit, row + 1, 0)
            grid.addWidget(label(hint, "hint", wrap=True), row + 2, 0)
        return grid

    def _toggle_key(self, visible: bool) -> None:
        self.fields["KV_GEMINI_API_KEY"].setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        self.show_key.setText("Ẩn key" if visible else "Hiện key")

    def _browse(self, key: str) -> None:
        if key == "KV_OUTPUT_DIR":
            path = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video", str(output_directory()))
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn font", "C:/Windows/Fonts", "Font (*.ttf *.otf)")
        if path:
            self.fields[key].setText(Path(path).as_posix())

    def load(self) -> None:
        for key, edit in self.fields.items():
            edit.setText(os.environ.get(key, ""))
        self.show_key.setChecked(False)

    def _values(self) -> dict[str, str] | None:
        values = {key: edit.text().strip() for key, edit in self.fields.items()}
        problems = []
        if values["KV_OLLAMA_URL"] and not values["KV_OLLAMA_URL"].startswith(("http://", "https://")):
            problems.append("Ollama URL phải bắt đầu bằng http:// hoặc https://.")
        timeout = values["KV_OLLAMA_TIMEOUT_SECONDS"]
        if timeout and not (timeout.replace(".", "", 1).isdigit() and float(timeout) > 0):
            problems.append("Ollama timeout phải là số giây lớn hơn 0.")
        font = values["KV_VIDEO_FONT"]
        if font and (not Path(font).is_file() or Path(font).suffix.lower() not in (".ttf", ".otf")):
            problems.append("Font phải là file .ttf hoặc .otf có trên máy.")
        folder = values["KV_OUTPUT_DIR"]
        if folder:
            try:
                Path(folder).expanduser().mkdir(parents=True, exist_ok=True)
            except OSError as error:
                problems.append(f"Không tạo được thư mục lưu video ({error.strerror}).")
        if problems:
            QMessageBox.warning(self, "Chưa lưu được", "\n".join(problems))
            return None
        return {key: Path(value).as_posix() if key in ("KV_OUTPUT_DIR", "KV_VIDEO_FONT") and value else value
                for key, value in values.items()}

    def _save(self) -> None:
        values = self._values()
        if values is None:
            return
        try:
            update_env(values)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Chưa lưu được", str(error))
            return
        self.saved.emit()
        QMessageBox.information(self, "Đã lưu", "Đã lưu cài đặt vào file .env.")
