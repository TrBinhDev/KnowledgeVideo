import html
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from core import catalog, images, sources, steps, timing, video_pipeline
from core.ai import build_provider, default_model, list_models
from core.config import RunStore, output_directory, slug
from core.preview import SCENES, render_preview, render_thumbnail, run_source
from core.render import _source_label, build_snapshot, export_video, import_music, make_thumbnail, render_video
from core.video_pipeline import transition_names
from ui import icons
from ui.history_page import HistoryPage
from ui.settings_page import SettingsPage
from ui.templates_page import TemplatesPage
from ui.widgets import Card, ChoiceCards, RenderProgress, Stepper, label
from ui.worker import TaskThread

STEPS = (
    ("Nội dung", "Loại nội dung & từ khóa"),
    ("Chủ đề", "AI gợi ý chủ đề"),
    ("Kịch bản", "Đề cương & lời đọc"),
    ("Cảnh & ảnh", "Ảnh cho từng cảnh"),
    ("Mẫu & Render", "Template & xuất video"),
)
TOPIC, SCRIPT, SCENES_PAGE, RENDER = 1, 2, 3, 4
CREATE, HISTORY, GALLERY, SETTINGS = 0, 1, 2, 3
SOURCE_LABELS = {
    "wikipedia": "Wikipedia", "wikipedia_topic": "Wikipedia - ảnh chung chủ đề, nên kiểm tra",
    "wikimedia": "Commons", "openverse": "Openverse",
    "pollinations": "AI Pollinations", "ai": "AI Gemini", "placeholder": "ảnh thay thế",
}
STAGE_LABELS = {
    "prepare_content": "Chuẩn bị nội dung", "prepare_assets": "Chuẩn bị ảnh", "generate_tts": "Tạo giọng đọc",
    "generate_subtitle": "Tạo phụ đề", "build_timeline": "Dựng timeline", "template_composition": "Ghép template",
    "ffmpeg_render": "Render FFmpeg", "validate": "Kiểm tra video",
}
# Content types shown for orientation only; the prototype implements "Kiến thức" (catalog.CONTENT_TYPES).
UPCOMING_TYPES = (
    ("Truyện tranh", "comic", "Kịch bản truyện tranh thành video"),
    ("Từ ảnh", "image", "Video chuyển động từ ảnh và prompt"),
    ("Tin tức", "news", "Tổng hợp tin tức thành video ngắn"),
)
TYPE_ICONS = {"kien_thuc": "book"}
CATEGORY_ICONS = {"lich_su": "clock"}


def _hint(text: str) -> QLabel:
    return label(text, "hint", wrap=True)


def _field(text: str) -> QLabel:
    return label(text, "fieldLabel")


def _buttons(*buttons: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addStretch(1)
    for button in buttons:
        row.addWidget(button)
    return row


def _button(text: str, name: str = "", icon: str | None = None, color: str = "#334155") -> QPushButton:
    button = QPushButton(text)
    if name:
        button.setObjectName(name)
    if icon:
        button.setIcon(icons.icon(icon, color, 16))
        button.setIconSize(QSize(16, 16))
    button.setCursor(Qt.PointingHandCursor)
    return button


def _primary(text: str, icon: str | None = None) -> QPushButton:
    return _button(text, "primary", icon, "#ffffff")


def _scroll(*cards: QWidget) -> QScrollArea:
    page = QWidget()
    page.setObjectName("page")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 8, 12)
    layout.setSpacing(16)
    for card in cards:
        layout.addWidget(card)
    layout.addStretch(1)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(page)
    return area


def _ranges(seconds: list[float]) -> list[str]:
    """Cumulative "[0-15s]" labels for consecutive durations."""
    labels, start = [], 0.0
    for value in seconds:
        end = start + value
        labels.append(f"[{round(start)}-{round(end)}s]")
        start = end
    return labels


def _folder_size(path: Path) -> int:
    try:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    except OSError:
        return 0


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Knowledge Video — Kiến thức lịch sử")
        self.resize(1320, 860)
        self.state: dict = {}
        self.store: RunStore | None = None
        self.task: TaskThread | None = None
        self.busy = False
        self.reached = 0
        self.render_active = False
        self.render_cancelling = False
        self.render_thread: dict = {}
        self.preferred_look: tuple[str, str] | None = None
        self.last_export_dir = ""
        self.scene_warnings: list[str] = []

        self.pages = QStackedWidget()
        for builder in (self._build_start, self._build_topic, self._build_script,
                        self._build_scenes, self._build_render):
            self.pages.addWidget(builder())
        self.pages.currentChanged.connect(self._on_page_changed)

        self.stepper = Stepper(list(STEPS))
        self.stepper.clicked.connect(self._on_step_clicked)
        step_bar = QFrame()
        step_bar.setObjectName("stepBar")
        step_layout = QVBoxLayout(step_bar)
        step_layout.setContentsMargins(16, 10, 16, 10)
        step_layout.addWidget(self.stepper)
        new_video = _button("Video mới", "soft", "plus", "#1d4ed8")
        new_video.clicked.connect(self._new_video)
        self.new_video_button = new_video
        create = QWidget()
        create_layout = QVBoxLayout(create)
        create_layout.setContentsMargins(0, 0, 0, 0)
        create_layout.setSpacing(8)
        create_layout.addWidget(step_bar)
        create_layout.addWidget(self.pages, 1)

        self.history_page = HistoryPage()
        self.history_page.open_requested.connect(self._open_run)
        self.templates_page = TemplatesPage()
        self.templates_page.use_requested.connect(self._use_look)
        self.settings_page = SettingsPage()
        self.settings_page.saved.connect(self._on_settings_saved)
        self.sections = QStackedWidget()
        self.section_headers = (
            ("Tạo video", "Tạo video kiến thức lịch sử từ chủ đề với AI: đề cương, kịch bản, ảnh tư liệu, "
                          "giọng đọc và render MP4.", new_video),
            ("Lịch sử video", "Mở lại video đã làm để sửa tiếp hoặc render lại.", None),
            ("Mẫu video", "Xem trước các mẫu giao diện, chuyển cảnh và chuyển động.", None),
            ("Cài đặt", "API key, model AI, thư mục lưu video và font chữ.", None),
        )
        for widget in (create, _scroll(self.history_page), _scroll(self.templates_page), _scroll(self.settings_page)):
            self.sections.addWidget(widget)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(6)
        self.page_title = label("", "pageTitle")
        self.page_subtitle = label("", "pageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles, 1)
        header.addWidget(new_video, 0, Qt.AlignBottom)
        content = QVBoxLayout()
        content.setContentsMargins(28, 22, 20, 0)
        content.setSpacing(6)
        content.addLayout(header)
        content.addSpacing(8)
        content.addWidget(self.sections, 1)

        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addLayout(content, 1)
        main.addWidget(self._build_status_bar())
        root = QHBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addLayout(main, 1)
        container = QWidget()
        container.setObjectName("app")
        container.setLayout(root)
        self.setCentralWidget(container)
        self._show_section(CREATE)
        self._go(0)

    # ---------- shell: sidebar, status bar, navigation ----------

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(2)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.pixmap("logo", "#2563eb", 30, 2.6))
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label("Knowledge Video", "brand"))
        names.addWidget(label("Video kiến thức lịch sử", "brandSub"))
        brand.addWidget(logo)
        brand.addLayout(names, 1)
        layout.addLayout(brand)
        layout.addSpacing(14)
        groups = (
            ("SẢN XUẤT", (("Tạo video", "film", CREATE),)),
            ("QUẢN LÝ", (("Lịch sử video", "clock", HISTORY), ("Mẫu video", "layout", GALLERY))),
            ("HỆ THỐNG", (("Cài đặt", "sliders", SETTINGS),)),
        )
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for title, items in groups:
            layout.addWidget(label(title, "navSection"))
            for text, icon_name, section in items:
                button = _button(f"  {text}", "navItem", icon_name, "#475569")
                button.setCheckable(True)
                self.nav.addButton(button, section)
                layout.addWidget(button)
        self.nav.idClicked.connect(self._show_section)
        layout.addStretch(1)
        storage = QFrame()
        storage.setObjectName("storage")
        box = QVBoxLayout(storage)
        box.setContentsMargins(12, 10, 12, 10)
        heading = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icons.pixmap("database", "#64748b", 16))
        heading.addWidget(mark)
        heading.addWidget(label("Thư mục output", "fieldLabel"), 1)
        box.addLayout(heading)
        self.storage_text = label("", "storageText", wrap=True)
        box.addWidget(self.storage_text)
        layout.addWidget(storage)
        self._update_storage()
        return sidebar

    def _update_storage(self) -> None:
        directory = output_directory()
        megabytes = _folder_size(directory) / 1024 / 1024
        runs = sum(1 for child in directory.iterdir() if child.is_dir() and (child / "state.json").is_file())
        self.storage_text.setText(f"{runs} video · {megabytes:,.0f} MB")
        self.storage_text.setToolTip(str(directory))

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("statusBar")
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(28, 8, 20, 8)
        layout.setSpacing(6)
        row = QHBoxLayout()
        self.status = label("Sẵn sàng.", "status")
        self.elapsed = label("", "hint")
        self.progress = QProgressBar()
        self.progress.setObjectName("thinBar")
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(220)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log_toggle = _button("Nhật ký", "link")
        self.log_toggle.setCheckable(True)
        row.addWidget(self.status, 1)
        row.addWidget(self.elapsed)
        row.addWidget(self.progress)
        row.addWidget(self.log_toggle)
        self.timeline = QListWidget()
        self.timeline.setObjectName("timeline")
        self.timeline.setFixedHeight(110)
        self.timeline.setVisible(False)
        self.log_toggle.toggled.connect(self.timeline.setVisible)
        layout.addLayout(row)
        layout.addWidget(self.timeline)
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(500)
        self.elapsed_timer.timeout.connect(self._tick)
        self.started_at = 0.0
        self.stage_started_at = 0.0
        self.current_stage = ""
        return bar

    def _go(self, index: int) -> None:
        self.reached = max(self.reached, index)
        self.stepper.set_state(index, self.reached)
        self.pages.setCurrentIndex(index)

    def _on_step_clicked(self, row: int) -> None:
        if 0 <= row <= self.reached and not self.busy:
            self.stepper.set_state(row, self.reached)
            self.pages.setCurrentIndex(row)

    def _reset_from(self, index: int) -> None:
        """Later steps depend on earlier ones; editing an earlier step invalidates them."""
        self.reached = index
        self._go(index)

    def _show_section(self, section: int) -> None:
        title, subtitle, _action = self.section_headers[section]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        self.new_video_button.setVisible(section == CREATE)
        self.nav.button(section).setChecked(True)
        if self.sections.currentIndex() == GALLERY and section != GALLERY:
            self.templates_page.deactivate()
        if section != CREATE:
            self.preview_player.pause()
        self.sections.setCurrentIndex(section)
        if section == CREATE:
            self._on_page_changed(self.pages.currentIndex())
        elif section == HISTORY:
            self.history_page.refresh()
        elif section == GALLERY:
            self.templates_page.activate()
        elif section == SETTINGS:
            self.settings_page.load()

    def _on_settings_saved(self) -> None:
        self._update_storage()
        self._log("Đã lưu cài đặt.")

    def _use_look(self, template: str, transition: str) -> None:
        """Gallery choice: applied to the render step now and whenever its templates are refilled."""
        self.preferred_look = (template, transition)
        self._apply_look()
        self._show_section(CREATE)
        self.status.setText(f"Đã chọn mẫu {self.template_cards.currentText()} · {self.transition_combo.currentText()} "
                            "cho video này.")

    def _apply_look(self) -> None:
        if not self.preferred_look:
            return
        template, transition = self.preferred_look
        if self.template_cards.findData(template) >= 0:
            self.template_cards.setCurrentIndex(self.template_cards.findData(template))
        self.transition_combo.setCurrentIndex(max(0, self.transition_combo.findData(transition)))

    def _reset_views(self) -> None:
        """Empty every step's widgets (before starting a new video or loading a saved one)."""
        self.preview_player.stop()
        self.input_edit.clear()
        self.source_edit.clear()
        self.topic_cards.clear()
        self.topic_edit.clear()
        self.outline_title.clear()
        self.outline_edit.clear()
        self.outline_toggle.setChecked(False)
        self.outline_view.setText("")
        self.outline_card.setEnabled(True)
        self.rewrite_button.setEnabled(True)
        self._clear_script()
        self.scene_list.clear()
        self.scene_preview.clear()
        self.scene_preview.setText("Chưa có ảnh")
        for widget in (self.scene_text, self.scene_credit, self.result_label):
            widget.setText("")
        self.scene_query_vi.clear()
        self.scene_query.clear()
        self.music_edit.clear()
        self.render_panel.setVisible(False)
        self.done_bar.setVisible(False)

    def _new_video(self) -> None:
        if self.busy:
            return
        self.state, self.store = {}, None
        self._reset_views()
        self.reached = 0
        self._show_section(CREATE)
        self._go(0)

    def _open_run(self, path: str) -> None:
        if self.busy:
            QMessageBox.information(self, "Đang bận", "Hãy đợi việc đang chạy xong rồi mở video khác.")
            return
        directory = Path(path)
        try:
            state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Không mở được", f"Không đọc được state.json ({type(error).__name__}).")
            return
        self._reset_views()
        self.store, self.state = RunStore(directory), state
        self._restore_inputs(state)
        if state.get("topics"):
            self._fill_topics(state["topics"])
        self.topic_edit.setText(state.get("topic", ""))
        reached = 1 if state.get("topics") or state.get("topic") else 0
        outline = state.get("outline")
        if outline:
            self.outline_title.setText(outline["title"])
            self.outline_edit.setPlainText(steps.outline_to_text(outline["points"]))
            self._render_outline_view()
            reached = SCRIPT
        if state.get("script"):
            self._fill_script(state["script"])
            if not outline:
                self._clear_outline()
            reached = SCRIPT
        scenes = state.get("scenes") or []
        if scenes:
            self._refresh_scene_list()
            reached = SCENES_PAGE
        self._show_section(CREATE)
        self.reached = reached
        if scenes and all(scene.get("image") for scene in scenes):
            self._to_render()
        else:
            self._go(reached)
        self._log(f"Mở lại: {directory.name}")

    def _restore_inputs(self, state: dict) -> None:
        """Step 1 choices of a saved run, without triggering the provider's model reload."""
        for cards, key in ((self.type_cards, "content_type"), (self.category_cards, "category")):
            if cards.findData(state.get(key)) >= 0:
                cards.setCurrentIndex(cards.findData(state.get(key)))
        self._show_duration(state.get("duration"))
        self.script_voice_combo.setCurrentIndex(max(0, self.script_voice_combo.findData(state.get("voice"))))
        if self.provider_cards.findData(state.get("provider")) >= 0:
            self.provider_cards.blockSignals(True)
            self.provider_cards.setCurrentIndex(self.provider_cards.findData(state["provider"]))
            self.provider_cards.blockSignals(False)
            self.model_combo.clear()
            self.model_combo.addItem(state.get("model") or default_model(state["provider"]))
        self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(state.get("style"))))
        self.points_combo.setCurrentIndex(max(0, self.points_combo.findData(state.get("points"))))
        from_source = state.get("mode") in ("source_ai", "source_verbatim")
        if from_source:
            self.source_edit.setPlainText(state.get("source", ""))
            self.source_mode.setCurrentIndex(1 if state["mode"] == "source_verbatim" else 0)
        else:
            self.input_edit.setPlainText(state.get("input", ""))
        self.input_tabs.button(1 if from_source else 0).setChecked(True)
        self.input_stack.setCurrentIndex(1 if from_source else 0)

    # ---------- progress and background work ----------

    def _log(self, text: str) -> None:
        self.timeline.addItem(f"{datetime.now():%H:%M:%S}  {text}")
        self.timeline.scrollToBottom()

    def _tick(self) -> None:
        self.elapsed.setText(f"{time.monotonic() - self.started_at:.0f} giây")

    def _close_stage(self) -> None:
        if self.current_stage:
            self._log(f"    xong: {self.current_stage} ({time.monotonic() - self.stage_started_at:.1f}s)")
        self.current_stage = ""

    def _on_progress(self, stage: str, percent: int) -> None:
        label_text = STAGE_LABELS.get(stage, stage)
        if label_text != self.current_stage:
            self._close_stage()
            self.current_stage, self.stage_started_at = label_text, time.monotonic()
        if self.render_active:
            self.render_panel.update_stage(stage, percent, label_text)
        if percent < 0:
            # Status-only update (e.g. which AI model is being called): keep the bar as it is.
            self.status.setText(label_text)
            return
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(percent)
        self.status.setText(f"{label_text} — {percent}%")

    def _run(self, message: str, job, on_success) -> None:
        # A flag rather than isRunning(): success callbacks may start the next job while the old thread is still exiting.
        if self.busy:
            return
        self.busy = True
        self._set_busy(True, message)
        # AI calls report no progress, so the bar stays in "busy" mode until a job emits a percentage.
        self.progress.setRange(0, 0)
        self.started_at = time.monotonic()
        self._log(f"Bắt đầu: {message}")
        self.elapsed_timer.start()
        self.task = TaskThread(job, self)
        self.task.progress.connect(self._on_progress)
        self.task.succeeded.connect(lambda result: (self._finish(True, "Xong"), on_success(result)))
        self.task.failed.connect(self._on_failed)
        self.task.start()

    def _finish(self, ok: bool, text: str) -> None:
        self.busy = False
        self._close_stage()
        self.elapsed_timer.stop()
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if ok else 0)
        took = time.monotonic() - self.started_at
        self._log(f"{text} ({took:.1f}s)")
        self._set_busy(False, f"{text} — {took:.1f} giây")

    def _on_failed(self, message: str) -> None:
        if self.render_active and self.render_cancelling:
            self._finish(False, "Đã hủy render")
            self.render_active = self.render_cancelling = False
            self.render_panel.finish(False, "Video trước đó (nếu có) vẫn được giữ nguyên.", "Đã hủy render")
            self._show_done_bar()
            return
        self._finish(False, "Lỗi: " + message)
        if self.render_active:
            self.render_active = False
            self.render_panel.finish(False, message)
        QMessageBox.warning(self, "Không thực hiện được", message)

    def _set_busy(self, busy: bool, message: str) -> None:
        if self.render_active:
            # Keep the page enabled so the render panel's cancel button can be pressed.
            self.render_controls.setEnabled(not busy)
            self.done_bar.setEnabled(not busy)
        else:
            self.pages.setEnabled(not busy)
        self.stepper.setEnabled(not busy)
        self.new_video_button.setEnabled(not busy)
        self.status.setText(message)

    def _ai_job(self, call):
        """Build the provider on the GUI thread from the current selection; `call(provider)` runs in the worker."""
        name = self.provider_cards.currentData()
        model = self.model_combo.currentText().strip() or default_model(name)
        # A failed attempt costs under a second, so trying several listed models is cheap.
        fallbacks = [self.model_combo.itemText(index) for index in range(self.model_combo.count())
                     if self.model_combo.itemText(index) != model][:8]
        provider = build_provider(name, model, fallbacks)
        self.state.update({"provider": name, "model": model})

        def job(progress):
            provider.notify = progress
            return call(provider)

        return job

    def _load_models(self) -> None:
        name = self.provider_cards.currentData()
        selected = self.model_combo.currentText().strip() or default_model(name)

        def done(models: list[str]) -> None:
            self.model_combo.clear()
            self.model_combo.addItems(models)
            if selected in models:
                self.model_combo.setCurrentText(selected)
            elif default_model(name) in models:
                self.model_combo.setCurrentText(default_model(name))
            if not models:
                QMessageBox.information(self, "Chưa có model", "Không có model nào dùng được cho lựa chọn này.")

        self._run(f"Lấy danh sách model {self.provider_cards.currentText()}", lambda _p: list_models(name), done)

    def _on_provider_changed(self) -> None:
        name = self.provider_cards.currentData()
        self.model_combo.clear()
        self.model_combo.addItem(default_model(name))
        self._load_models()

    def _save(self) -> None:
        if self.store:
            self.store.save(self.state)

    # ---------- step 1: content ----------

    def _build_start(self) -> QWidget:
        kind = Card("Chọn loại nội dung", "Chọn dạng nội dung bạn muốn tạo video", "layout")
        self.type_cards = ChoiceCards(columns=4, tile=True, art_size=QSize(0, 84))
        for key, info in catalog.CONTENT_TYPES.items():
            self.type_cards.addItem(info["label"], key, "Video giáo dục, giải thích chủ đề bằng AI",
                                    TYPE_ICONS.get(key, "book"))
        for title, icon_name, subtitle in UPCOMING_TYPES:
            self.type_cards.addItem(title, None, subtitle, icon_name, badge="Sắp có", enabled=False)
        kind.body.addWidget(self.type_cards)
        kind.body.addWidget(_field("Danh mục"))
        self.category_cards = ChoiceCards(columns=4)
        for key, info in catalog.CONTENT_TYPES["kien_thuc"]["categories"].items():
            self.category_cards.addItem(info["label"], key, "Mốc thời gian, nhân vật, diễn biến",
                                        CATEGORY_ICONS.get(key, "book"))
        kind.body.addWidget(self.category_cards)

        ai = Card("AI viết nội dung", "Model chọn ở đây dùng cho mọi bước AI sau. Gemini quá tải sẽ tự thử "
                  "các model khác trong danh sách.", "sparkles")
        self.provider_cards = ChoiceCards(columns=2)
        self.provider_cards.addItem("Gemini", "gemini", "Google, cần API key (bản free dùng được)", "sparkles")
        self.provider_cards.addItem("Ollama", "ollama", "Chạy trên máy, không cần mạng cho AI", "chip")
        self.provider_cards.setCurrentIndex(1)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItem(default_model("ollama"))
        refresh_models = _button("Làm mới", "soft", "refresh", "#1d4ed8")
        refresh_models.clicked.connect(self._load_models)
        self.provider_cards.currentIndexChanged.connect(self._on_provider_changed)
        self.duration_combo = QComboBox()
        self.duration_combo.setEditable(True)
        self.duration_combo.setInsertPolicy(QComboBox.NoInsert)
        self.duration_combo.setToolTip(f"Chọn sẵn hoặc gõ số giây ({catalog.MIN_DURATION}–{catalog.MAX_DURATION}).")
        for seconds in catalog.DURATIONS:
            self.duration_combo.addItem(f"{seconds} giây", seconds)
        self.duration_combo.setCurrentIndex(1)
        # The script length is fitted with this voice; the render step can still switch and refit.
        self.script_voice_combo = QComboBox()
        for key, name in catalog.VOICES.items():
            self.script_voice_combo.addItem(name, key)
        settings = QGridLayout()
        settings.setHorizontalSpacing(12)
        settings.setVerticalSpacing(4)
        settings.addWidget(_field("Model"), 0, 0)
        settings.addWidget(_field("Độ dài video"), 0, 2)
        settings.addWidget(_field("Giọng đọc"), 0, 3)
        settings.addWidget(self.model_combo, 1, 0)
        settings.addWidget(refresh_models, 1, 1)
        settings.addWidget(self.duration_combo, 1, 2)
        settings.addWidget(self.script_voice_combo, 1, 3)
        self.style_combo = QComboBox()
        for key, (name, _instruction) in catalog.STYLES.items():
            self.style_combo.addItem(name, key)
        self.points_combo = QComboBox()
        for count in catalog.POINT_COUNTS:
            self.points_combo.addItem("Tự động theo độ dài" if count is None else f"{count} ý", count)
        settings.addWidget(_field("Phong cách lời kể"), 2, 0)
        settings.addWidget(_field("Số ý chính"), 2, 2)
        settings.addWidget(self.style_combo, 3, 0, 1, 2)
        settings.addWidget(self.points_combo, 3, 2)
        settings.setColumnStretch(0, 3)
        settings.setColumnStretch(2, 2)
        settings.setColumnStretch(3, 2)
        ai.body.addWidget(self.provider_cards)
        ai.body.addLayout(settings)

        source = Card("Nhập nội dung / Từ khóa", "Nhập từ khóa để AI gợi ý chủ đề, hoặc đưa nội dung có sẵn "
                      "(bài viết, tài liệu) để làm video bám theo đúng tài liệu đó.", "search")
        import_json = _button("Nhập kịch bản JSON", "soft", "file", "#1d4ed8")
        import_json.clicked.connect(self._import_script_json)
        source.actions.addWidget(import_json)
        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self.input_tabs = QButtonGroup(self)
        self.input_stack = QStackedWidget()
        for index, text in enumerate(("Nhập từ khóa gợi ý từ AI", "Nhập nội dung trực tiếp")):
            tab = _button(text, "tab")
            tab.setCheckable(True)
            tab.setChecked(index == 0)
            self.input_tabs.addButton(tab, index)
            tabs.addWidget(tab)
        tabs.addStretch(1)
        self.input_tabs.idClicked.connect(self.input_stack.setCurrentIndex)
        source.body.addLayout(tabs)

        keywords = QWidget()
        keywords_layout = QVBoxLayout(keywords)
        keywords_layout.setContentsMargins(0, 0, 0, 0)
        self.input_edit = QPlainTextEdit()
        self.input_edit.setFixedHeight(84)
        self.input_edit.setPlaceholderText("Ví dụ: trận Bạch Đằng, nhà Trần chống quân Nguyên")
        keywords_layout.addWidget(self.input_edit)
        keywords_layout.addWidget(_hint("Gợi ý: tên trận đánh, triều đại, nhân vật, sự kiện hoặc mốc năm cụ thể."))
        suggest = _primary("AI gợi ý chủ đề", "sparkles")
        direct = _button("Dùng làm chủ đề luôn")
        suggest.clicked.connect(self._suggest_topics)
        direct.clicked.connect(self._use_input_as_topic)
        keywords_layout.addLayout(_buttons(direct, suggest))

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.source_edit = QPlainTextEdit()
        self.source_edit.setMinimumHeight(200)
        self.source_edit.setPlaceholderText("Dán nội dung bài viết/tài liệu lịch sử vào đây, hoặc tải file lên. "
                                            "Dòng đầu ngắn, không có dấu chấm sẽ được coi là tiêu đề.")
        self.source_edit.textChanged.connect(self._update_source_count)
        content_layout.addWidget(self.source_edit)
        file_row = QHBoxLayout()
        upload = _button("Tải file (txt, docx, pdf)", icon="file")
        upload.clicked.connect(self._load_source_file)
        self.source_count = _hint("")
        file_row.addWidget(upload)
        file_row.addWidget(_hint("Tối đa 10MB; PDF dạng ảnh scan chưa đọc được."), 1)
        file_row.addWidget(self.source_count)
        content_layout.addLayout(file_row)
        content_layout.addWidget(_field("Cách dùng nội dung"))
        self.source_mode = ChoiceCards(columns=2)
        self.source_mode.addItem("AI tóm tắt thành kịch bản", "summarize",
                                 "AI lập đề cương và viết lời đọc, chỉ dùng dữ kiện trong tài liệu", "sparkles")
        self.source_mode.addItem("Dùng nguyên văn", "verbatim",
                                 "Không tóm tắt: nội dung của bạn chính là lời đọc", "file")
        content_layout.addWidget(self.source_mode)
        from_source = _primary("Tiếp tục với nội dung này →")
        from_source.clicked.connect(self._use_source)
        content_layout.addLayout(_buttons(from_source))
        self.input_stack.addWidget(keywords)
        self.input_stack.addWidget(content)
        source.body.addWidget(self.input_stack)
        return _scroll(kind, ai, source)

    def _duration(self) -> int | None:
        """Length typed or picked in the duration box ("75", "75 giây"), None (with a message) when out of range."""
        match = re.search(r"\d+", self.duration_combo.currentText())
        seconds = int(match.group()) if match else 0
        if not catalog.MIN_DURATION <= seconds <= catalog.MAX_DURATION:
            QMessageBox.information(self, "Độ dài chưa hợp lệ",
                                    f"Độ dài video phải từ {catalog.MIN_DURATION} đến {catalog.MAX_DURATION} giây.")
            return None
        return seconds

    def _show_duration(self, seconds: int | None) -> None:
        index = self.duration_combo.findData(seconds)
        if index >= 0:
            self.duration_combo.setCurrentIndex(index)
        elif seconds:
            self.duration_combo.setEditText(f"{seconds} giây")

    def _read_settings(self) -> bool:
        """Step 1 choices shared by every way of starting a video; False when the duration is invalid."""
        duration = self._duration()
        if duration is None:
            return False
        self.state.update({
            "content_type": self.type_cards.currentData(), "category": self.category_cards.currentData(),
            "duration": duration, "voice": self.script_voice_combo.currentData(),
            "style": self.style_combo.currentData(), "points": self.points_combo.currentData(),
        })
        return True

    def _read_start(self) -> str | None:
        text = self.input_edit.toPlainText().strip()
        if len(text) < 3:
            QMessageBox.information(self, "Thiếu nội dung", "Hãy nhập từ khóa hoặc chủ đề (ít nhất 3 ký tự).")
            return None
        if not self._read_settings():
            return None
        self.state.update({"input": text, "mode": "keywords"})
        self.state.pop("source", None)
        return text

    def _update_source_count(self) -> None:
        count = len(self.source_edit.toPlainText().strip())
        cut = " (sẽ dùng 15.000 ký tự đầu)" if count > sources.MAX_SOURCE_CHARS else ""
        self.source_count.setText(f"{count:,} ký tự{cut}".replace(",", "."))

    def _load_source_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn tài liệu", "", "Tài liệu (*.txt *.md *.docx *.pdf)")
        if not path:
            return

        self._run(f"Đọc file {Path(path).name}", lambda _p: sources.read_document(Path(path)),
                  self.source_edit.setPlainText)

    def _start_run(self, topic: str) -> None:
        """New run folder for a video started from content or JSON (no topic step)."""
        self.store = RunStore.create(topic)
        for key in ("topics", "outline", "script", "scenes", "video", "image_subject", "render"):
            self.state.pop(key, None)
        self.state["topic"] = topic
        self.topic_cards.clear()
        self.topic_edit.setText(topic)

    def _use_source(self) -> None:
        text = self.source_edit.toPlainText().strip()
        if len(text) < 50:
            QMessageBox.information(self, "Nội dung quá ngắn", "Hãy nhập hoặc tải nội dung dài ít nhất vài câu.")
            return
        if not self._read_settings():
            return
        source, cut = sources.limit(text)
        mode = self.source_mode.currentData()
        title = sources.title_line(source) or " ".join(source.split()[:14])
        self._start_run(title[:90])
        self.state.update({"input": source[:300], "source": source,
                           "mode": "source_verbatim" if mode == "verbatim" else "source_ai"})
        if cut:
            self._log("Nội dung dài quá, chỉ dùng 15.000 ký tự đầu.")
        if mode == "verbatim":
            try:
                parts = sources.split_narration(source)
            except sources.SourceError as error:
                QMessageBox.information(self, "Chưa dùng được nội dung", str(error))
                return
            script = {"title": parts["title"] or title[:90], "hook": parts["hook"], "body": parts["body"]}
            self._fit_imported(script)
            return
        self._save()
        self._make_outline()

    def _fit_imported(self, script: dict, then=None) -> None:
        """Script not written by the AI: measure it and tune only the speaking rate, never rewrite it."""
        duration, voice = self.state["duration"], self._voice()
        self.state["outline"] = None
        self._save()

        def done(fitted: dict) -> None:
            self._clear_outline()
            self._show_script(fitted)
            if then:
                then()

        self._run("Đo thời lượng giọng đọc",
                  lambda progress: steps.fit_script_duration(None, "", "", script, duration, voice, progress), done)

    def _import_script_json(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Nhập kịch bản JSON")
        dialog.resize(720, 560)
        layout = QVBoxLayout(dialog)
        layout.addWidget(_hint("Dán kịch bản dạng JSON (ví dụ do Claude/ChatGPT viết). Cần \"title\", \"hook\", "
                               "\"paragraphs\"; \"outline\" và \"scenes\" (lời đọc + từ khóa ảnh mỗi cảnh) là tùy chọn. "
                               "Có \"scenes\" thì bỏ qua bước AI chia cảnh."))
        editor = QPlainTextEdit()
        editor.setPlaceholderText(steps.SCRIPT_JSON_EXAMPLE)
        layout.addWidget(editor, 1)
        open_file = _button("Mở file .json", icon="folder")
        example = _button("Chèn mẫu")
        cancel = _button("Hủy")
        accept = _primary("Nhập")
        open_file.clicked.connect(lambda: self._read_json_file(editor))
        example.clicked.connect(lambda: editor.setPlainText(steps.SCRIPT_JSON_EXAMPLE))
        cancel.clicked.connect(dialog.reject)
        accept.clicked.connect(dialog.accept)
        row = QHBoxLayout()
        row.addWidget(open_file)
        row.addWidget(example)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(accept)
        layout.addLayout(row)
        while dialog.exec() == QDialog.Accepted:
            try:
                imported = steps.parse_script_json(editor.toPlainText())
            except steps.ScriptImportError as error:
                QMessageBox.warning(self, "JSON chưa đúng", str(error))
                continue
            self._apply_imported(imported)
            return

    def _read_json_file(self, editor: QPlainTextEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn file JSON", "", "JSON (*.json)")
        if path:
            try:
                editor.setPlainText(Path(path).read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError) as error:
                QMessageBox.warning(self, "Không đọc được file", type(error).__name__)

    def _apply_imported(self, imported: dict) -> None:
        if not self._read_settings():
            return
        script = imported["script"]
        self._start_run(script["title"][:90])
        self.state.update({"input": script["title"], "mode": "json"})
        self.state.pop("source", None)
        outline = imported["outline"]
        if outline:
            seconds = steps.normalize_seconds([point["seconds"] for point in outline], self.state["duration"])
            outline = [{"text": point["text"], "seconds": value} for point, value in zip(outline, seconds)]
        scenes = imported["scenes"]
        subject = imported["subject"]

        def after_fit() -> None:
            if outline:
                self.state["outline"] = {"title": script["title"], "points": outline, "approved": True}
                self._save()
                self.outline_card.setEnabled(True)
                self.outline_title.setText(script["title"])
                self.outline_edit.setPlainText(steps.outline_to_text(outline))
                self._render_outline_view()
            if scenes:
                self.state["script"]["approved"] = True
                self._show_scenes({"subject": subject, "scenes": scenes})

        self._fit_imported(script, after_fit)

    def _voice(self) -> str:
        """Voice the script is measured with: the one chosen in step 1, saved in the run."""
        return self.state.get("voice") or self.script_voice_combo.currentData()

    def _suggest_topics(self) -> None:
        text = self._read_start()
        if text is None:
            return
        state = dict(self.state)
        self._run("AI đang gợi ý chủ đề...",
                  self._ai_job(lambda provider: steps.suggest_topics(provider, state["content_type"], state["category"], text)),
                  self._show_topics)

    def _use_input_as_topic(self) -> None:
        text = self._read_start()
        if text is None:
            return
        self._show_topics([{"title": text, "angle": ""}])

    # ---------- step 2: topic ----------

    def _build_topic(self) -> QWidget:
        card = Card("Gợi ý chủ đề từ AI", "Chọn 1 chủ đề, có thể sửa lại tên trước khi tạo đề cương.", "sparkles")
        again = _button("Làm mới gợi ý", "soft", "refresh", "#1d4ed8")
        own = _button("Tự nhập chủ đề", "soft", "plus", "#1d4ed8")
        again.clicked.connect(self._suggest_topics)
        own.clicked.connect(self._own_topic)
        card.actions.addWidget(again)
        card.actions.addWidget(own)
        self.topic_cards = ChoiceCards(columns=2, indicator=True)
        self.topic_cards.currentIndexChanged.connect(self._on_topic_selected)
        card.body.addWidget(self.topic_cards)
        card.body.addWidget(_field("Chủ đề đã chọn"))
        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("Chủ đề video")
        card.body.addWidget(self.topic_edit)
        next_button = _primary("Tạo đề cương →")
        next_button.clicked.connect(self._make_outline)
        card.body.addLayout(_buttons(next_button))
        return _scroll(card)

    def _show_topics(self, topics: list[dict]) -> None:
        self.state["topics"] = topics
        self._fill_topics(topics)
        self.topic_cards.setCurrentIndex(0)
        self._reset_from(TOPIC)

    def _fill_topics(self, topics: list[dict]) -> None:
        self.topic_cards.clear()
        for index, topic in enumerate(topics):
            self.topic_cards.addItem(topic["title"], index, topic.get("angle", ""))

    def _on_topic_selected(self, row: int) -> None:
        topics = self.state.get("topics") or []
        if 0 <= row < len(topics):
            self.topic_edit.setText(topics[row]["title"])

    def _own_topic(self) -> None:
        self.topic_cards.setCurrentIndex(-1)
        self.topic_edit.clear()
        self.topic_edit.setFocus()

    def _make_outline(self) -> None:
        topic = self.topic_edit.text().strip()
        if len(topic) < 3:
            QMessageBox.information(self, "Thiếu chủ đề", "Hãy chọn hoặc nhập chủ đề.")
            return
        if self.state.get("topic") != topic or self.store is None:
            self.store = RunStore.create(topic)
            for key in ("outline", "script", "scenes", "video"):
                self.state.pop(key, None)
        self.state["topic"] = topic
        self._save()
        state = dict(self.state)
        self._run("AI đang lập đề cương...",
                  self._ai_job(lambda provider: steps.make_outline(
                      provider, state["content_type"], state["category"], topic, state["duration"],
                      state.get("points"), state.get("style"), state.get("source", ""))),
                  self._show_outline)

    # ---------- step 3: outline and script ----------

    def _build_script(self) -> QWidget:
        outline = Card("Đề cương", "Mỗi ý kèm thời lượng; tổng luôn bằng độ dài video đã chọn.", "list")
        self.outline_card = outline
        self.outline_toggle = _button("Chỉnh sửa", "link", "edit", "#2563eb")
        self.outline_toggle.setCheckable(True)
        self.outline_toggle.toggled.connect(self._toggle_outline_edit)
        outline.actions.addWidget(self.outline_toggle)
        self.outline_stack = QStackedWidget()
        self.outline_view = label("", "outlineView", wrap=True)
        self.outline_view.setTextFormat(Qt.RichText)
        self.outline_view.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.addWidget(_field("Tiêu đề"))
        self.outline_title = QLineEdit()
        editor_layout.addWidget(self.outline_title)
        editor_layout.addWidget(_hint("Mỗi dòng một ý, dạng \"20s | nội dung\". Sửa số giây để ý đó dài/ngắn hơn; "
                                      "khi xác nhận, số giây được chia lại cho tổng đúng bằng thời lượng đã chọn."))
        self.outline_edit = QPlainTextEdit()
        self.outline_edit.setMinimumHeight(180)
        self.outline_edit.textChanged.connect(self._update_outline_total)
        editor_layout.addWidget(self.outline_edit)
        self.outline_stack.addWidget(self.outline_view)
        self.outline_stack.addWidget(editor)
        outline.body.addWidget(self.outline_stack)
        self.outline_total = _hint("")
        outline.body.addWidget(self.outline_total)
        again = _button("Tạo lại đề cương", icon="refresh")
        approve = _primary("Xác nhận dùng đề cương")
        again.clicked.connect(self._make_outline)
        approve.clicked.connect(self._write_script)
        outline.body.addLayout(_buttons(again, approve))

        self.script_card = Card("Kịch bản", "Lời đọc đầy đủ. Kiểm tra kỹ năm tháng, tên người, địa danh: "
                                "AI có thể viết sai với nội dung lịch sử.", "file")
        self.script_toggle = _button("Chỉnh sửa", "link", "edit", "#2563eb")
        self.script_toggle.setCheckable(True)
        self.script_toggle.toggled.connect(self._toggle_script_edit)
        self.script_card.actions.addWidget(self.script_toggle)
        self.script_stack = QStackedWidget()
        self.script_view = label("", "scriptView", wrap=True)
        self.script_view.setTextFormat(Qt.RichText)
        self.script_view.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self.script_title = QLineEdit()
        self.script_hook = QPlainTextEdit()
        self.script_hook.setFixedHeight(70)
        self.script_body = QPlainTextEdit()
        self.script_body.setMinimumHeight(260)
        for widget in (self.script_hook, self.script_body):
            widget.textChanged.connect(self._update_script_stats)
        editor_layout.addWidget(_field("Tiêu đề"))
        editor_layout.addWidget(self.script_title)
        editor_layout.addWidget(_field("Hook (câu mở đầu)"))
        editor_layout.addWidget(self.script_hook)
        editor_layout.addWidget(_field("Thân bài (các đoạn cách nhau một dòng trống)"))
        editor_layout.addWidget(self.script_body)
        self.script_stack.addWidget(self.script_view)
        self.script_stack.addWidget(editor)
        self.script_card.body.addWidget(self.script_stack)
        self.script_stats = _hint("")
        self.script_card.body.addWidget(self.script_stats)
        again = _button("Viết lại", icon="refresh")
        again.setToolTip("AI viết lại lời đọc theo đề cương.")
        self.rewrite_button = again
        measure = _button("Đo lại thời lượng", icon="clock")
        approve = _primary("Xác nhận kịch bản → Chia cảnh")
        again.clicked.connect(self._write_script)
        measure.clicked.connect(self._remeasure_script)
        approve.clicked.connect(self._split_scenes)
        self.script_card.body.addLayout(_buttons(again, measure, approve))
        self._clear_script()
        return _scroll(outline, self.script_card)

    def _outline_points(self) -> list[dict]:
        return steps.parse_outline_text(self.outline_edit.toPlainText(), self.state.get("duration", 0))

    def _render_outline_view(self) -> None:
        points = self._outline_points()
        title = html.escape(self.outline_title.text().strip() or self.state.get("topic", ""))
        lines = [f"<p style='font-weight:600; color:#0f172a'>Tiêu đề: {title}</p>"]
        for rng, point in zip(_ranges([point["seconds"] for point in points]), points):
            lines.append(f"<p><span style='color:#2563eb; font-weight:600'>{rng}</span> {html.escape(point['text'])}</p>")
        self.outline_view.setText("".join(lines))

    def _toggle_outline_edit(self, editing: bool) -> None:
        if not editing:
            self._render_outline_view()
        self.outline_toggle.setText("Xong" if editing else "Chỉnh sửa")
        self.outline_stack.setCurrentIndex(1 if editing else 0)

    def _show_outline(self, outline: dict) -> None:
        self.state["outline"] = outline
        self._save()
        self.outline_card.setEnabled(True)
        self.rewrite_button.setEnabled(True)
        self.outline_title.setText(outline["title"])
        self.outline_edit.setPlainText(steps.outline_to_text(outline["points"]))
        self.outline_toggle.setChecked(False)
        self._render_outline_view()
        self._clear_script()
        self._reset_from(SCRIPT)

    def _clear_outline(self) -> None:
        """Script used as given (verbatim content or JSON without an outline): no outline, no AI rewrite."""
        self.outline_title.clear()
        self.outline_edit.clear()
        self.outline_toggle.setChecked(False)
        reason = {"source_verbatim": "Dùng nguyên văn nội dung bạn nhập nên không có đề cương.",
                  "json": "Kịch bản nhập từ JSON, không kèm đề cương."}.get(self.state.get("mode"), "Không có đề cương.")
        self.outline_view.setText(f"<p style='color:#94a3b8'>{reason}</p>")
        self.outline_card.setEnabled(False)
        self.rewrite_button.setEnabled(False)

    def _update_outline_total(self) -> None:
        typed = sum(int(match.group(1)) for line in self.outline_edit.toPlainText().splitlines()
                    if (match := re.match(r"^\s*(\d+)\s*s?\s*\|", line)))
        target = self.state.get("duration", 0)
        note = "" if typed == target else " — khi xác nhận sẽ tự chia lại cho khớp"
        self.outline_total.setText(f"Tổng: {typed} giây / mục tiêu {target} giây{note}")

    def _write_script(self) -> None:
        duration = self.state["duration"]
        points = self._outline_points()
        title = self.outline_title.text().strip() or self.state["topic"]
        if len(points) < 2:
            QMessageBox.information(self, "Đề cương quá ngắn", "Đề cương cần ít nhất 2 ý.")
            return
        self.state["outline"] = {"title": title, "points": points, "approved": True}
        self._save()
        self.outline_edit.setPlainText(steps.outline_to_text(points))
        self.outline_toggle.setChecked(False)
        self._render_outline_view()
        state = dict(self.state)
        voice = self._voice()

        def write_and_fit(provider):
            script = steps.write_script(provider, state["content_type"], state["category"], state["topic"], title, points,
                                        state.get("style"), state.get("source", ""))
            return steps.fit_script_duration(provider, state["content_type"], state["category"], script,
                                             duration, voice, provider.notify, state.get("style"))

        self._run("AI đang viết kịch bản và canh thời lượng...", self._ai_job(write_and_fit), self._show_script)

    def _clear_script(self) -> None:
        for widget in (self.script_title, self.script_hook, self.script_body):
            widget.blockSignals(True)
            widget.clear()
            widget.blockSignals(False)
        self.script_toggle.setChecked(False)
        self.script_view.setText("<p style='color:#94a3b8'>Xác nhận đề cương để AI viết kịch bản.</p>")
        self.script_stats.setText("")
        self.script_card.setEnabled(False)

    def _script_from_editor(self) -> dict:
        return {"title": self.script_title.text().strip(), "hook": self.script_hook.toPlainText().strip(),
                "body": self.script_body.toPlainText().strip()}

    def _script_seconds(self, hook: str, body: str) -> tuple[float, bool]:
        """Measured narration length when the text is unchanged since the last measurement, else an estimate."""
        fitted = (self.state.get("script") or {}).get("timing")
        if fitted and fitted.get("narration") == timing.narration({"hook": hook, "body": body}):
            return float(fitted["seconds"]), True
        return float(steps.estimated_seconds(hook, body)), False

    def _render_script_view(self) -> None:
        script = self._script_from_editor()
        parts = [script["hook"]] + [part.strip() for part in re.split(r"\n\s*\n", script["body"]) if part.strip()]
        total, _measured = self._script_seconds(script["hook"], script["body"])
        words = [max(1, steps.word_count(part)) for part in parts]
        seconds = [total * count / sum(words) for count in words]
        lines = [f"<p style='font-weight:600; color:#0f172a'>Tiêu đề: {html.escape(script['title'])}</p>"]
        for index, (rng, part) in enumerate(zip(_ranges(seconds), parts)):
            name = "<b>Hook:</b> " if index == 0 else ""
            lines.append(f"<p><span style='color:#2563eb; font-weight:600'>{rng}</span> {name}{html.escape(part)}</p>")
        self.script_view.setText("".join(lines))

    def _toggle_script_edit(self, editing: bool) -> None:
        if not editing and self.script_card.isEnabled():
            self._render_script_view()
        self.script_toggle.setText("Xong" if editing else "Chỉnh sửa")
        self.script_stack.setCurrentIndex(1 if editing else 0)

    def _remeasure_script(self) -> None:
        """Keep the user's wording: only the speaking rate is tuned (no AI rewrite)."""
        script = self._script_from_editor()
        if not script["hook"] or not script["body"]:
            return
        duration, voice = self.state["duration"], self._voice()

        def job(progress):
            return steps.fit_script_duration(None, "", "", script, duration, voice, progress)

        def done(fitted):
            self.state["script"] = {**self.state.get("script", {}), **fitted}
            self._save()
            self._update_script_stats()
            if not self.script_toggle.isChecked():
                self._render_script_view()

        self._run("Đo thời lượng giọng đọc", job, done)

    def _show_script(self, script: dict) -> None:
        self.state["script"] = script
        self._save()
        self._fill_script(script)
        self._reset_from(SCRIPT)

    def _fill_script(self, script: dict) -> None:
        self.script_card.setEnabled(True)
        self.script_title.setText(script["title"])
        self.script_hook.setPlainText(script["hook"])
        self.script_body.setPlainText(script["body"])
        self.script_toggle.setChecked(False)
        self._render_script_view()

    def _update_script_stats(self) -> None:
        hook, body = self.script_hook.toPlainText(), self.script_body.toPlainText()
        words = steps.word_count(hook) + steps.word_count(body)
        target = self.state.get("duration", 0)
        fitted = (self.state.get("script") or {}).get("timing")
        if fitted and fitted.get("narration") == timing.narration({"hook": hook, "body": body}):
            if fitted["within_tolerance"]:
                status = "khớp"
            elif self.state.get("outline"):
                status = f"lệch quá {timing.TOLERANCE_SECONDS:.0f}s, nên Viết lại"
            else:
                # Text used as written is never rewritten by the AI; only the user can change its length.
                direction = "ngắn" if fitted["seconds"] < target else "dài"
                status = (f"{direction} hơn mục tiêu quá {timing.TOLERANCE_SECONDS:.0f}s: sửa thêm/bớt nội dung "
                          "(Chỉnh sửa) rồi Đo lại, hoặc cứ render với độ dài này")
            self.script_stats.setText(
                f"{words} từ — đo thật: {fitted['seconds']}s (tốc độ đọc {fitted['tts_rate']}) / "
                f"mục tiêu {target}s — {status}")
        else:
            self.script_stats.setText(
                f"{words} từ, ước tính ~{steps.estimated_seconds(hook, body)}s / mục tiêu {target}s — "
                "đã sửa tay, bấm \"Đo lại thời lượng\" (render cũng tự canh lại)")

    def _split_scenes(self) -> None:
        script = self._script_from_editor()
        if not all(script.values()):
            QMessageBox.information(self, "Kịch bản chưa đủ", "Tiêu đề, hook và thân bài đều không được để trống.")
            return
        self.state["script"] = {**self.state.get("script", {}), **script, "approved": True}
        self._save()
        duration, topic = self.state["duration"], self.state.get("topic", "")
        self._run("AI đang chia cảnh...",
                  self._ai_job(lambda provider: steps.split_scenes(provider, script["title"], topic, script["hook"],
                                                                   script["body"], duration, provider.notify)),
                  self._show_scenes)

    # ---------- step 4: scenes and images ----------

    def _build_scenes(self) -> QWidget:
        card = Card("Cảnh & ảnh", "Mỗi cảnh tự tìm ảnh theo từ khóa riêng: Commons (Việt, Anh) → Wikipedia tiếng Việt "
                    "→ Openverse → ảnh chung của chủ đề → Pollinations (nếu bật) → ảnh thay thế. "
                    "Ảnh AI chỉ là minh họa, không phải tư liệu thật.", "image")
        self.pollinations_check = QCheckBox("Dùng ảnh AI Pollinations khi thiếu ảnh thật")
        self.pollinations_check.setToolTip("Ảnh AI miễn phí (Pollinations), chỉ dùng khi không tìm được ảnh thật cho cảnh.")
        self.pollinations_check.setChecked(True)
        card.body.addWidget(self.pollinations_check)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.scene_list = QListWidget()
        self.scene_list.setIconSize(QSize(72, 128))
        self.scene_list.setWordWrap(True)
        self.scene_list.setMinimumHeight(520)
        self.scene_list.currentRowChanged.connect(self._show_scene_detail)
        body.addWidget(self.scene_list, 1)
        detail = QVBoxLayout()
        self.scene_preview = QLabel("Chưa có ảnh")
        self.scene_preview.setAlignment(Qt.AlignCenter)
        self.scene_preview.setFixedSize(270, 480)
        self.scene_preview.setObjectName("preview")
        self.scene_text = QLabel()
        self.scene_text.setWordWrap(True)
        self.scene_query_vi = QLineEdit()
        self.scene_query_vi.setPlaceholderText("Từ khóa tìm ảnh tiếng Việt (vd: cọc Bạch Đằng)")
        self.scene_query_vi.editingFinished.connect(self._save_scene_query)
        self.scene_query = QLineEdit()
        self.scene_query.setPlaceholderText("Từ khóa tìm ảnh tiếng Anh (vd: Bach Dang stakes)")
        self.scene_query.editingFinished.connect(self._save_scene_query)
        self.scene_credit = QLabel()
        self.scene_credit.setWordWrap(True)
        self.scene_credit.setObjectName("hint")
        self.scene_credit.setTextFormat(Qt.RichText)
        self.scene_credit.setOpenExternalLinks(True)
        other = _button("Ảnh Wikimedia khác", icon="refresh")
        pollinations = _button("Ảnh AI (Pollinations)", icon="sparkles")
        ai = _button("Ảnh AI (Gemini)", icon="sparkles")
        ai.setToolTip("Cần Gemini API key có bật billing.")
        other.clicked.connect(self._next_wikimedia)
        pollinations.clicked.connect(self._pollinations_image)
        ai.clicked.connect(self._ai_image)
        detail.addWidget(self.scene_preview, 0, Qt.AlignHCenter)
        detail.addWidget(self.scene_text)
        detail.addWidget(_field("Từ khóa tìm ảnh"))
        detail.addWidget(self.scene_query_vi)
        detail.addWidget(self.scene_query)
        detail.addWidget(self.scene_credit)
        detail.addLayout(_buttons(other))
        detail.addLayout(_buttons(pollinations, ai))
        detail.addStretch(1)
        # Fixed width: long unbreakable text (credits, keywords) must not widen this column and squeeze the list.
        detail_panel = QWidget()
        detail_panel.setFixedWidth(320)
        detail_panel.setLayout(detail)
        body.addWidget(detail_panel)
        card.body.addLayout(body)
        resplit = _button("Chia cảnh lại", icon="refresh")
        fetch = _button("Tìm lại ảnh thiếu", icon="search")
        fetch.setToolTip("Tìm lại ảnh cho các cảnh chưa có ảnh hoặc đang dùng ảnh thay thế.")
        next_button = _primary("Tiếp tục → Chọn mẫu")
        resplit.clicked.connect(self._split_scenes)
        fetch.clicked.connect(self._fetch_missing_images)
        next_button.clicked.connect(self._to_render)
        card.body.addLayout(_buttons(resplit, fetch, next_button))
        return _scroll(card)

    def _show_scenes(self, result: dict) -> None:
        self.state["image_subject"] = result["subject"]
        self.state["scenes"] = result["scenes"]
        # Shown together with the image search messages, which follow right away.
        self.scene_warnings = list(result.get("warnings") or [])
        self._save()
        self._refresh_scene_list()
        self._reset_from(SCENES_PAGE)
        self._fetch_missing_images()

    def _refresh_scene_list(self, select: int = 0) -> None:
        self.scene_list.blockSignals(True)
        self.scene_list.clear()
        for index, scene in enumerate(self.state.get("scenes") or []):
            image = scene.get("image")
            source = SOURCE_LABELS.get((image or {}).get("source"), "chưa có ảnh")
            item = QListWidgetItem(f"Cảnh {index + 1} [{source}]\n{scene['text'][:140]}")
            if image:
                item.setIcon(QIcon(QPixmap(str(self.store.assets / image["file"]))))
            self.scene_list.addItem(item)
        self.scene_list.blockSignals(False)
        if self.scene_list.count():
            self.scene_list.setCurrentRow(min(select, self.scene_list.count() - 1))
            self._show_scene_detail(self.scene_list.currentRow())

    def _show_scene_detail(self, row: int) -> None:
        scenes = self.state.get("scenes") or []
        if not 0 <= row < len(scenes):
            return
        scene = scenes[row]
        self.scene_text.setText(scene["text"])
        self.scene_query_vi.setText(scene.get("image_query_vi", ""))
        self.scene_query.setText(scene.get("image_query_en", ""))
        image = scene.get("image")
        if image:
            pixmap = QPixmap(str(self.store.assets / image["file"]))
            self.scene_preview.setPixmap(pixmap.scaled(self.scene_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            text = f"Nguồn: {html.escape(image.get('credit', ''))}"
            page = image.get("page", "")
            if page.startswith(("https://", "http://")):
                text += f' · <a href="{html.escape(page, quote=True)}">Xem trang gốc</a>'
            self.scene_credit.setText(text)
        else:
            self.scene_preview.setText("Chưa có ảnh")
            self.scene_credit.setText("")

    def _save_scene_query(self) -> None:
        row = self.scene_list.currentRow()
        scenes = self.state.get("scenes") or []
        if not 0 <= row < len(scenes):
            return
        changed = False
        for key, field in (("image_query_vi", self.scene_query_vi), ("image_query_en", self.scene_query)):
            value = field.text().strip()
            if value and scenes[row].get(key) != value:
                scenes[row][key], changed = value, True
        if changed:
            scenes[row]["seen_urls"] = []
            self._save()

    def _used_urls(self, exclude: int) -> set[str]:
        return {(scene.get("image") or {}).get("url") for index, scene in enumerate(self.state["scenes"])
                if index != exclude and (scene.get("image") or {}).get("url")}

    def _fetch_missing_images(self) -> None:
        """Fill scenes that have no image or only a placeholder."""
        scenes = self.state.get("scenes") or []
        store = self.store
        topic = self.state.get("topic", "")
        title = (self.state.get("script") or {}).get("title", topic)
        use_pollinations = self.pollinations_check.isChecked()
        subject = self.state.get("image_subject") or {}

        def job(progress):
            errors = []
            progress("Tìm ảnh chung của chủ đề trên Wikipedia tiếng Việt", 0)
            try:
                # Short subject name ("Bạch Đằng") matches articles far better than the whole topic sentence.
                pool = images.wikipedia_vi_pool(subject.get("vi") or topic)
            except (OSError, ValueError) as error:
                pool = []
                errors.append(f"Không đọc được Wikipedia tiếng Việt ({type(error).__name__}).")
            for index, scene in enumerate(scenes):
                progress(f"Lấy ảnh cảnh {index + 1}/{len(scenes)}", round(5 + index * 95 / len(scenes)))
                if (scene.get("image") or {}).get("source") not in (None, "placeholder"):
                    continue
                try:
                    scene["image"], warnings = images.fetch_scene_image(
                        scene, store.assets, index, self._used_urls(index), topic, title, pool, use_pollinations, subject)
                    errors.extend(warnings)
                except images.ImageError as error:
                    errors.append(str(error))
            progress(f"Lấy ảnh cảnh {len(scenes)}/{len(scenes)}", 100)
            return errors

        self._run("Lấy ảnh cho các cảnh", job, self._after_images)

    def _after_images(self, errors: list[str]) -> None:
        self._save()
        self._refresh_scene_list(self.scene_list.currentRow())
        notes, self.scene_warnings = self.scene_warnings + errors, []
        if notes:
            QMessageBox.warning(self, "Cần kiểm tra một số cảnh", "\n".join(notes))

    def _next_wikimedia(self) -> None:
        row = self.scene_list.currentRow()
        if row < 0:
            return
        self._save_scene_query()
        scene = self.state["scenes"][row]
        seen = set(scene.get("seen_urls") or [])
        current_url = (scene.get("image") or {}).get("url")
        if current_url:
            seen.add(current_url)
        used = self._used_urls(row) | seen
        store = self.store

        def done(image):
            if not image:
                QMessageBox.information(self, "Hết ảnh", "Wikimedia không còn ảnh phù hợp cho từ khóa này. "
                                                        "Hãy đổi từ khóa hoặc tạo ảnh AI.")
                return
            scene["image"] = image
            scene["seen_urls"] = sorted(seen | {image["url"]})
            self._save()
            self._refresh_scene_list(row)

        def job(_progress):
            for query in (scene.get("image_query_vi"), scene.get("image_query_en")):
                image = images.from_wikimedia(query, store.assets, row, used) if query else None
                image = image or images.from_wikipedia(query or "", store.assets, row, used)
                if image:
                    return image
            return None

        self._run("Đang tìm ảnh Wikimedia khác...", job, done)

    def _pollinations_image(self) -> None:
        row = self.scene_list.currentRow()
        if row < 0:
            return
        scene = self.state["scenes"][row]
        store = self.store

        def done(image):
            scene["image"] = image
            self._save()
            self._refresh_scene_list(row)

        self._run("Pollinations đang tạo ảnh...",
                  lambda _p: images.from_pollinations(scene["image_prompt"], store.assets, row), done)

    def _ai_image(self) -> None:
        row = self.scene_list.currentRow()
        if row < 0:
            return
        scene = self.state["scenes"][row]
        store = self.store

        def done(image):
            scene["image"] = image
            self._save()
            self._refresh_scene_list(row)

        self._run("Gemini đang tạo ảnh...", lambda _p: images.from_ai(scene["image_prompt"], store.assets, row), done)

    def _to_render(self) -> None:
        missing = [str(index + 1) for index, scene in enumerate(self.state.get("scenes") or []) if not scene.get("image")]
        if missing:
            QMessageBox.information(self, "Còn cảnh thiếu ảnh", f"Các cảnh chưa có ảnh: {', '.join(missing)}.")
            return
        self._fill_templates(self.state.get("content_type", "kien_thuc"))
        self._restore_render_options()
        self._apply_look()
        self.render_panel.setVisible(False)
        self._show_done_bar()
        self._go(RENDER)
        self._update_specs()
        self._load_thumbnails()

    def _restore_render_options(self) -> None:
        """Choices of the last render of this run, else the voice the script was measured with."""
        options = self.state.get("render") or {}
        self.voice_combo.setCurrentIndex(max(0, self.voice_combo.findData(options.get("voice") or self._voice())))
        if not options:
            return
        if self.template_cards.findData(options.get("template")) >= 0:
            self.template_cards.setCurrentIndex(self.template_cards.findData(options["template"]))
        self.transition_combo.setCurrentIndex(max(0, self.transition_combo.findData(options.get("transition", "template"))))
        self.timing_combo.setCurrentIndex(max(0, self.timing_combo.findData(options.get("scene_timing"))))
        self.subtitle_combo.setCurrentIndex(max(0, self.subtitle_combo.findData(options.get("subtitle_style"))))
        self.resolution_combo.setCurrentIndex(max(0, self.resolution_combo.findData(options.get("resolution"))))
        self.volume_spin.setValue(int(options.get("music_volume", 15)))
        music = options.get("music_source", "")
        self.music_edit.setText(music if music and Path(music).is_file() else "")

    def _show_done_bar(self) -> None:
        video = Path(self.state["video"]) if self.state.get("video") else None
        if not video or not video.is_file():
            self.done_bar.setVisible(False)
            return
        thumbnail = video.with_name("thumbnail.jpg")
        if thumbnail.is_file():
            self.done_cover.setPixmap(QPixmap(str(thumbnail)).scaledToHeight(96, Qt.SmoothTransformation))
        else:
            self.done_cover.setPixmap(icons.pixmap("box-checked", "#16a34a", 26))
        self.result_label.setText(str(video))
        self.done_bar.setVisible(True)

    # ---------- step 5: template and render ----------

    def _fill_templates(self, content_type: str) -> None:
        """Only templates of the current content type are offered (history styles are separate from news)."""
        current = self.template_cards.currentData()
        self.template_cards.clear()
        for key, name in catalog.TEMPLATES_BY_TYPE.get(content_type, catalog.NEWS_TEMPLATES).items():
            title, _, style = name.partition(" (")
            self.template_cards.addItem(title, key, style.rstrip(")"))
        index = self.template_cards.findData(current)
        self.template_cards.setCurrentIndex(max(0, index))

    def _build_render(self) -> QWidget:
        card = Card("Chọn mẫu giao diện & Tạo video", "Chọn phong cách khung hình, chuyển cảnh và xuất video.", "layout")
        self.template_cards = ChoiceCards(columns=3, tile=True, art_size=QSize(0, 210))
        self._fill_templates("kien_thuc")
        self.voice_combo = QComboBox()
        for key, name in catalog.VOICES.items():
            self.voice_combo.addItem(name, key)
        self.transition_combo = QComboBox()
        for key, name in catalog.TRANSITIONS.items():
            self.transition_combo.addItem(name, key)
        self.resolution_combo = QComboBox()
        for value in catalog.RESOLUTIONS:
            self.resolution_combo.addItem(value, value)
        self.music_edit = QLineEdit()
        self.music_edit.setReadOnly(True)
        self.music_edit.setPlaceholderText("Không dùng nhạc nền")
        browse = _button("Chọn...", icon="music")
        clear = _button("Bỏ")
        browse.clicked.connect(self._choose_music)
        clear.clicked.connect(self.music_edit.clear)
        self.volume_spin = QSpinBox()
        self.volume_spin.setRange(0, 100)
        self.volume_spin.setValue(15)
        self.volume_spin.setSuffix(" %")
        # The styled frame leaves no room for the arrow buttons; typing and the mouse wheel still work.
        self.volume_spin.setButtonSymbols(QSpinBox.NoButtons)
        # Debounced: refilling the template cards fires several index changes in a row.
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(200)
        self.preview_timer.timeout.connect(self._update_preview)
        # Lambdas: connected directly, the int index would be taken as QTimer.start(msec).
        self.template_cards.currentIndexChanged.connect(lambda _index: self.preview_timer.start())
        self.transition_combo.currentIndexChanged.connect(lambda _index: self.preview_timer.start())
        self.timing_combo = QComboBox()
        for key, name in catalog.SCENE_TIMINGS.items():
            self.timing_combo.addItem(name, key)
        self.timing_combo.setToolTip("Theo câu đọc: mỗi ảnh xuất hiện đúng lúc giọng đọc nói tới cảnh đó. "
                                     "Chia đều: mọi ảnh dài bằng nhau.")
        self.subtitle_combo = QComboBox()
        for key, name in catalog.SUBTITLE_STYLES.items():
            self.subtitle_combo.addItem(name, key)
        self.subtitle_combo.setToolTip("Highlight từng từ: từ đang đọc đổi màu, kiểu TikTok.")
        for widget in (self.template_cards, self.transition_combo, self.voice_combo, self.resolution_combo,
                       self.timing_combo, self.subtitle_combo):
            widget.currentIndexChanged.connect(lambda _index: self._update_specs())

        options = QGridLayout()
        options.setHorizontalSpacing(12)
        options.setVerticalSpacing(4)
        choices = (("Giọng đọc", self.voice_combo), ("Chuyển cảnh", self.transition_combo),
                   ("Độ phân giải", self.resolution_combo), ("Nhịp ảnh", self.timing_combo),
                   ("Phụ đề", self.subtitle_combo))
        for index, (name, widget) in enumerate(choices):
            # Voice, transition, resolution on the first row; music sits between; image rhythm and subtitles last.
            row, column = (0 if index < 3 else 4), index % 3
            options.addWidget(_field(name), row, column)
            options.addWidget(widget, row + 1, column)
        music_row = QHBoxLayout()
        music_row.addWidget(self.music_edit, 1)
        music_row.addWidget(browse)
        music_row.addWidget(clear)
        options.addWidget(_field("Nhạc nền"), 2, 0, 1, 2)
        options.addWidget(_field("Âm lượng nhạc"), 2, 2)
        options.addLayout(music_row, 3, 0, 1, 2)
        options.addWidget(self.volume_spin, 3, 2)
        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(self.template_cards)
        left.addWidget(_field("Tùy chỉnh"))
        left.addLayout(options)
        left.addStretch(1)

        side = QVBoxLayout()
        side.setSpacing(10)
        self.preview_video = QVideoWidget()
        self.preview_video.setFixedSize(270, 480)
        self.preview_player = QMediaPlayer(self)
        self.preview_player.setVideoOutput(self.preview_video)
        self.preview_player.setLoops(QMediaPlayer.Loops.Infinite)
        self.preview_hint = _hint("Xem trước dùng ảnh và tiêu đề của video này (không có chuyển động, phụ đề, giọng đọc).")
        side.addWidget(_field("Xem trước"))
        side.addWidget(self.preview_video, 0, Qt.AlignHCenter)
        side.addWidget(self.preview_hint)
        side.addWidget(self._build_specs())
        side.addStretch(1)
        side_panel = QWidget()
        side_panel.setFixedWidth(300)
        side_panel.setLayout(side)
        body = QHBoxLayout()
        body.setSpacing(20)
        body.addLayout(left, 1)
        body.addWidget(side_panel)
        # Disabled while rendering instead of the whole page, so the progress panel's cancel button stays usable.
        self.render_controls = QWidget()
        controls = QVBoxLayout(self.render_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(12)
        controls.addLayout(body)
        card.body.addWidget(self.render_controls)

        cta = QFrame()
        cta.setObjectName("ctaBar")
        cta_layout = QHBoxLayout(cta)
        cta_layout.setContentsMargins(16, 12, 16, 12)
        mark = QLabel()
        mark.setPixmap(icons.pixmap("sparkles", "#2563eb", 26))
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label("Sẵn sàng tạo video", "ctaTitle"))
        self.cta_detail = _hint("")
        texts.addWidget(self.cta_detail)
        render_button = _primary("Tạo video với mẫu đã chọn", "play")
        render_button.clicked.connect(self._render)
        cta_layout.addWidget(mark)
        cta_layout.addLayout(texts, 1)
        cta_layout.addWidget(render_button)
        controls.addWidget(cta)

        self.render_panel = RenderProgress()
        self.render_panel.setVisible(False)
        self.render_panel.cancel_requested.connect(self._cancel_render)
        card.body.addWidget(self.render_panel)

        self.done_bar = QFrame()
        self.done_bar.setObjectName("doneBar")
        done_layout = QHBoxLayout(self.done_bar)
        done_layout.setContentsMargins(16, 12, 16, 12)
        done_layout.setSpacing(14)
        self.done_cover = QLabel()
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label("Video đã hoàn thành", "ctaTitle"))
        texts.addWidget(_hint("Kèm ảnh bìa thumbnail.jpg và phụ đề SRT/VTT trong cùng thư mục."))
        self.result_label = _hint("")
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        texts.addWidget(self.result_label)
        texts.addStretch(1)
        self.open_folder = _button("Mở thư mục", icon="folder")
        self.export_button = _button("Xuất video", "soft", "folder", "#1d4ed8")
        self.open_video = _primary("Xem video", "play")
        self.open_video.clicked.connect(lambda: self._open(self.state.get("video")))
        self.open_folder.clicked.connect(lambda: self._open(str(self.store.directory) if self.store else None))
        self.export_button.clicked.connect(self._export_video)
        done_layout.addWidget(self.done_cover)
        done_layout.addLayout(texts, 1)
        done_layout.addWidget(self.open_folder)
        done_layout.addWidget(self.export_button)
        done_layout.addWidget(self.open_video)
        self.done_bar.setVisible(False)
        card.body.addWidget(self.done_bar)

        self.preview_running = False
        self.preview_pending = False
        self.thumbnails_running = False
        return _scroll(card)

    def _build_specs(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(label("Thông số kỹ thuật", "panelTitle"), 1)
        self.spec_tag = label("Sẵn sàng", "okTag")
        heading.addWidget(self.spec_tag)
        layout.addLayout(heading)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.spec_values = {}
        for row, key in enumerate(("Độ phân giải", "Tỷ lệ khung hình", "Giọng đọc", "Thời lượng", "Chuyển cảnh",
                                   "Nhịp ảnh", "Phụ đề", "Số cảnh", "Nguồn ảnh", "Định dạng", "Dung lượng")):
            value = label("", "specValue", wrap=True)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(label(key, "specKey"), row, 0)
            grid.addWidget(value, row, 1)
            self.spec_values[key] = value
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return panel

    def _update_specs(self) -> None:
        scenes = self.state.get("scenes") or []
        script = self.state.get("script") or {}
        seconds, measured = self._script_seconds(script.get("hook", ""), script.get("body", ""))
        video = Path(self.state["video"]) if self.state.get("video") else None
        values = {
            "Độ phân giải": self.resolution_combo.currentData() or "",
            "Tỷ lệ khung hình": "9:16 (dọc)",
            "Giọng đọc": self.voice_combo.currentText(),
            "Thời lượng": f"{'' if measured else '~'}{seconds:.0f} giây",
            "Chuyển cảnh": self.transition_combo.currentText(),
            "Nhịp ảnh": self.timing_combo.currentText(),
            "Phụ đề": self.subtitle_combo.currentText(),
            "Số cảnh": str(len(scenes)),
            "Nguồn ảnh": _source_label(scenes) if scenes else "",
            "Định dạng": "MP4 (H.264 / AAC)",
            "Dung lượng": f"{video.stat().st_size / 1024 / 1024:.1f} MB" if video and video.is_file() else "sau khi render",
        }
        for key, value in values.items():
            self.spec_values[key].setText(value)
        self.cta_detail.setText(f"{len(scenes)} cảnh · kịch bản {values['Thời lượng']} · "
                                f"Mẫu: {self.template_cards.currentText()} · {self.transition_combo.currentText()}")

    def _load_thumbnails(self) -> None:
        """Title-card frame of every template, rendered in the background and cached per run."""
        if not self.store or self.thumbnails_running:
            return
        self.thumbnails_running = True
        store, state = self.store, self.state
        templates = [self.template_cards.itemData(index) for index in range(self.template_cards.count())]

        def job(_progress):
            source = run_source(store, state, 1)
            return {template: str(render_thumbnail(source, template)) for template in templates}

        def done(paths: dict) -> None:
            self.thumbnails_running = False
            for template, path in paths.items():
                index = self.template_cards.findData(template)
                if index >= 0:
                    self.template_cards.setItemPixmap(index, QPixmap(path))

        def failed(message: str) -> None:
            self.thumbnails_running = False
            self._log(f"Không tạo được ảnh mẫu: {message}")

        self.thumbnail_task = TaskThread(job, self)
        self.thumbnail_task.succeeded.connect(done)
        self.thumbnail_task.failed.connect(failed)
        self.thumbnail_task.start()

    def _update_preview(self) -> None:
        template, transition = self.template_cards.currentData(), self.transition_combo.currentData()
        if not self.store or template is None or self.pages.currentIndex() != RENDER:
            return
        # One preview render at a time; a change made meanwhile is rendered right after it.
        if self.preview_running:
            self.preview_pending = True
            return
        self.preview_running = True
        names = transition_names(template, transition, SCENES - 1)
        labels = " → ".join(dict.fromkeys(catalog.TRANSITIONS.get(name, name) for name in names))
        self.preview_hint.setText(f"Đang tạo xem trước: {self.template_cards.currentText()} — {labels}...")
        store, state = self.store, self.state
        self.preview_task = TaskThread(
            lambda _p: str(render_preview(run_source(store, state), template, transition)), self)
        self.preview_task.succeeded.connect(lambda path: self._on_preview_done(path, labels))
        self.preview_task.failed.connect(lambda message: self._on_preview_done(None, message))
        self.preview_task.start()

    def _on_preview_done(self, path: str | None, text: str) -> None:
        self.preview_running = False
        if self.preview_pending:
            self.preview_pending = False
            self._update_preview()
            return
        if path:
            self.preview_player.setSource(QUrl.fromLocalFile(path))
            self.preview_player.play()
            self.preview_hint.setText(f"Chuyển cảnh: {text}. Xem trước không có chuyển động, phụ đề, giọng đọc.")
        else:
            self.preview_hint.setText(f"Không tạo được xem trước: {text}")

    def _on_page_changed(self, index: int) -> None:
        if index == RENDER:
            self.preview_timer.start()
        else:
            self.preview_player.pause()

    def _choose_music(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn nhạc nền", "", "Audio (*.mp3 *.wav *.m4a)")
        if path:
            self.music_edit.setText(path)

    def _render(self) -> None:
        options = {"voice": self.voice_combo.currentData(), "template": self.template_cards.currentData(),
                   "transition": self.transition_combo.currentData(),
                   "scene_timing": self.timing_combo.currentData(), "subtitle_style": self.subtitle_combo.currentData(),
                   "resolution": self.resolution_combo.currentData(), "music_volume": self.volume_spin.value(),
                   "music_source": self.music_edit.text()}
        self.state["render"] = options
        self._save()
        store, state = self.store, self.state
        self.done_bar.setVisible(False)
        self.result_label.setText("")
        worker = self.render_thread = {}

        def job(progress):
            worker["id"] = threading.get_ident()

            def step(stage, percent):
                # A cancel stops the job at the next progress report (e.g. between TTS measurements).
                video_pipeline.check_cancelled()
                progress(stage, percent)

            try:
                # Re-fit against the voice actually chosen for rendering (speaking speed differs per voice).
                script = state["script"]
                fitted = script.get("timing") or {}
                if fitted.get("voice") != options["voice"] or fitted.get("narration") != timing.narration(script):
                    fitted = timing.fit_rate(timing.narration(script), options["voice"], state["duration"], step)
                    script["timing"] = fitted
                snapshot = build_snapshot(state, options, import_music(store, options["music_source"]),
                                          fitted["tts_rate"])
                return str(render_video(store, snapshot, step))
            finally:
                video_pipeline.clear_cancel(worker["id"])

        def done(video_path):
            self.render_active = self.render_cancelling = False
            self.state["video"] = video_path
            self._save()
            self.render_panel.finish(True, video_path)
            self._show_done_bar()
            self._update_specs()
            self._update_storage()
            self._scroll_to(self.done_bar)

        self.render_panel.setVisible(True)
        self.render_panel.start()
        self.render_active, self.render_cancelling = True, False
        self._run("Render video", job, done)
        self._scroll_to(self.render_panel)

    def _cancel_render(self) -> None:
        if not self.render_active:
            return
        self.render_cancelling = True
        if "id" not in self.render_thread:
            # The worker has not started yet; try again once it has recorded its thread.
            QTimer.singleShot(200, self._cancel_render)
            return
        self._log("Yêu cầu hủy render")
        video_pipeline.cancel_thread(self.render_thread["id"])

    def _export_video(self) -> None:
        video = Path(self.state.get("video") or "")
        if not video.is_file():
            QMessageBox.information(self, "Chưa có video", "Hãy render video trước.")
            return
        title = (self.state.get("script") or {}).get("title") or self.state.get("topic") or "video"
        folder = self.last_export_dir or QStandardPaths.writableLocation(QStandardPaths.MoviesLocation)
        target, _ = QFileDialog.getSaveFileName(self, "Xuất video", str(Path(folder) / f"{slug(title)}.mp4"),
                                                "Video MP4 (*.mp4)")
        if not target:
            return
        self.last_export_dir = str(Path(target).parent)

        def job(_progress):
            if not video.with_name("thumbnail.jpg").is_file():
                make_thumbnail(video)
            return export_video(video, Path(target))

        def done(files: list[Path]):
            names = "\n".join(path.name for path in files)
            QMessageBox.information(self, "Đã xuất video", f"Đã lưu vào {Path(target).parent}:\n{names}")

        self._run("Xuất video", job, done)

    def _scroll_to(self, widget: QWidget) -> None:
        # After the layout has placed the newly shown widget.
        QTimer.singleShot(50, lambda: self.pages.widget(RENDER).ensureWidgetVisible(widget, 0, 16))

    def _open(self, path: str | None) -> None:
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
