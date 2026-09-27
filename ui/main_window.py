import re
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QCheckBox, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from core import catalog, images, steps, timing
from core.ai import build_provider, default_model, list_models
from core.config import RunStore
from core.render import build_snapshot, import_music, render_video
from ui.worker import TaskThread

STEP_NAMES = ("1. Bắt đầu", "2. Chọn chủ đề", "3. Đề cương", "4. Kịch bản", "5. Cảnh & ảnh", "6. Render")
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


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("heading")
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def _buttons(*buttons: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addStretch(1)
    for button in buttons:
        row.addWidget(button)
    return row


def _primary(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("primary")
    return button


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Knowledge Video — Kiến thức lịch sử")
        self.resize(1180, 760)
        self.state: dict = {}
        self.store: RunStore | None = None
        self.task: TaskThread | None = None
        self.busy = False
        self.reached = 0

        self.steps_list = QListWidget()
        self.steps_list.setObjectName("steps")
        self.steps_list.setFixedWidth(200)
        for name in STEP_NAMES:
            self.steps_list.addItem(name)
        self.steps_list.currentRowChanged.connect(self._on_step_clicked)

        self.pages = QStackedWidget()
        for builder in (self._build_start, self._build_topic, self._build_outline,
                        self._build_script, self._build_scenes, self._build_render):
            self.pages.addWidget(builder())

        right = QVBoxLayout()
        right.addWidget(self.pages, 1)
        right.addWidget(self._build_progress_panel())
        root = QHBoxLayout()
        root.addWidget(self.steps_list)
        root.addLayout(right, 1)
        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)
        self._go(0)

    # ---------- navigation and background work ----------

    def _go(self, index: int) -> None:
        self.reached = max(self.reached, index)
        for row in range(self.steps_list.count()):
            item = self.steps_list.item(row)
            flags = item.flags()
            item.setFlags(flags | Qt.ItemIsEnabled if row <= self.reached else flags & ~Qt.ItemIsEnabled)
        self.steps_list.blockSignals(True)
        self.steps_list.setCurrentRow(index)
        self.steps_list.blockSignals(False)
        self.pages.setCurrentIndex(index)

    def _on_step_clicked(self, row: int) -> None:
        if 0 <= row <= self.reached:
            self.pages.setCurrentIndex(row)

    def _reset_from(self, index: int) -> None:
        """Later steps depend on earlier ones; editing an earlier step invalidates them."""
        self.reached = index
        self._go(index)

    # ---------- progress panel and timeline ----------

    def _build_progress_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("progressPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 6, 0, 0)
        row = QHBoxLayout()
        self.status = QLabel("Sẵn sàng.")
        self.status.setObjectName("status")
        self.elapsed = QLabel("")
        self.elapsed.setObjectName("hint")
        row.addWidget(self.status, 1)
        row.addWidget(self.elapsed)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.timeline = QListWidget()
        self.timeline.setObjectName("timeline")
        self.timeline.setFixedHeight(110)
        layout.addLayout(row)
        layout.addWidget(self.progress)
        layout.addWidget(self.timeline)
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(500)
        self.elapsed_timer.timeout.connect(self._tick)
        self.started_at = 0.0
        self.stage_started_at = 0.0
        self.current_stage = ""
        return panel

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
        label = STAGE_LABELS.get(stage, stage)
        if label != self.current_stage:
            self._close_stage()
            self.current_stage, self.stage_started_at = label, time.monotonic()
        if percent < 0:
            # Status-only update (e.g. which AI model is being called): keep the bar as it is.
            self.status.setText(label)
            return
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(percent)
        self.status.setText(f"{label} — {percent}%")

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
        self._finish(False, "Lỗi: " + message)
        QMessageBox.warning(self, "Không thực hiện được", message)

    def _set_busy(self, busy: bool, message: str) -> None:
        self.pages.setEnabled(not busy)
        self.steps_list.setEnabled(not busy)
        self.status.setText(message)

    def _ai_job(self, call):
        """Build the provider on the GUI thread from the current selection; `call(provider)` runs in the worker."""
        name = self.provider_combo.currentData()
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
        name = self.provider_combo.currentData()
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

        self._run(f"Lấy danh sách model {self.provider_combo.currentText()}", lambda _p: list_models(name), done)

    def _on_provider_changed(self) -> None:
        name = self.provider_combo.currentData()
        self.model_combo.clear()
        self.model_combo.addItem(default_model(name))
        self._load_models()

    def _save(self) -> None:
        if self.store:
            self.store.save(self.state)

    # ---------- step 1: start ----------

    def _build_start(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_heading("Bắt đầu"))
        layout.addWidget(_hint("Nhập từ khóa để AI gợi ý chủ đề, hoặc nhập thẳng chủ đề/nội dung muốn làm video. "
                               "Model chọn ở đây dùng cho mọi bước AI sau, kể cả khi bấm tạo lại; "
                               "Gemini quá tải sẽ tự thử các model khác trong danh sách."))
        form = QFormLayout()
        self.type_combo = QComboBox()
        for key, info in catalog.CONTENT_TYPES.items():
            self.type_combo.addItem(info["label"], key)
        self.category_combo = QComboBox()
        for key, info in catalog.CONTENT_TYPES["kien_thuc"]["categories"].items():
            self.category_combo.addItem(info["label"], key)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Ollama (local)", "ollama")
        self.provider_combo.addItem("Gemini", "gemini")
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItem(default_model("ollama"))
        refresh_models = QPushButton("Làm mới")
        refresh_models.clicked.connect(self._load_models)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(refresh_models)
        self.duration_combo = QComboBox()
        for seconds in catalog.DURATIONS:
            self.duration_combo.addItem(f"{seconds} giây", seconds)
        self.duration_combo.setCurrentIndex(1)
        form.addRow("Loại nội dung", self.type_combo)
        form.addRow("Danh mục", self.category_combo)
        form.addRow("AI viết kịch bản", self.provider_combo)
        form.addRow("Model", model_row)
        form.addRow("Thời lượng", self.duration_combo)
        layout.addLayout(form)
        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText("Ví dụ: trận Bạch Đằng, nhà Trần chống quân Nguyên")
        layout.addWidget(self.input_edit, 1)
        suggest = _primary("AI gợi ý chủ đề")
        direct = QPushButton("Dùng làm chủ đề luôn")
        suggest.clicked.connect(self._suggest_topics)
        direct.clicked.connect(self._use_input_as_topic)
        layout.addLayout(_buttons(direct, suggest))
        return page

    def _read_start(self) -> str | None:
        text = self.input_edit.toPlainText().strip()
        if len(text) < 3:
            QMessageBox.information(self, "Thiếu nội dung", "Hãy nhập từ khóa hoặc chủ đề (ít nhất 3 ký tự).")
            return None
        self.state.update({
            "content_type": self.type_combo.currentData(), "category": self.category_combo.currentData(),
            "duration": self.duration_combo.currentData(), "input": text,
        })
        return text

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
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_heading("Chọn chủ đề"))
        layout.addWidget(_hint("Chọn một gợi ý, có thể sửa lại tên chủ đề trước khi tạo đề cương."))
        self.topic_list = QListWidget()
        self.topic_list.setWordWrap(True)
        self.topic_list.currentRowChanged.connect(self._on_topic_selected)
        layout.addWidget(self.topic_list, 1)
        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("Chủ đề video")
        layout.addWidget(self.topic_edit)
        again = QPushButton("Gợi ý lại")
        next_button = _primary("Tạo đề cương →")
        again.clicked.connect(self._suggest_topics)
        next_button.clicked.connect(self._make_outline)
        layout.addLayout(_buttons(again, next_button))
        return page

    def _show_topics(self, topics: list[dict]) -> None:
        self.state["topics"] = topics
        self.topic_list.clear()
        for topic in topics:
            text = topic["title"] + (f"\n{topic['angle']}" if topic["angle"] else "")
            self.topic_list.addItem(text)
        self.topic_list.setCurrentRow(0)
        self._reset_from(1)

    def _on_topic_selected(self, row: int) -> None:
        topics = self.state.get("topics") or []
        if 0 <= row < len(topics):
            self.topic_edit.setText(topics[row]["title"])

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
                  self._ai_job(lambda provider: steps.make_outline(provider, state["content_type"], state["category"],
                                                                   topic, state["duration"])),
                  self._show_outline)

    # ---------- step 3: outline ----------

    def _build_outline(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_heading("Đề cương"))
        layout.addWidget(_hint("Mỗi dòng một ý, dạng \"20s | nội dung\". Sửa số giây để ý đó dài/ngắn hơn; "
                               "khi duyệt, số giây được chia lại cho tổng đúng bằng thời lượng đã chọn."))
        self.outline_title = QLineEdit()
        layout.addWidget(self.outline_title)
        self.outline_edit = QPlainTextEdit()
        self.outline_edit.textChanged.connect(self._update_outline_total)
        layout.addWidget(self.outline_edit, 1)
        self.outline_total = QLabel()
        layout.addWidget(self.outline_total)
        again = QPushButton("Tạo lại đề cương")
        approve = _primary("Duyệt → Viết kịch bản")
        again.clicked.connect(self._make_outline)
        approve.clicked.connect(self._write_script)
        layout.addLayout(_buttons(again, approve))
        return page

    def _show_outline(self, outline: dict) -> None:
        self.state["outline"] = outline
        self._save()
        self.outline_title.setText(outline["title"])
        self.outline_edit.setPlainText(steps.outline_to_text(outline["points"]))
        self._reset_from(2)

    def _update_outline_total(self) -> None:
        typed = sum(int(match.group(1)) for line in self.outline_edit.toPlainText().splitlines()
                    if (match := re.match(r"^\s*(\d+)\s*s?\s*\|", line)))
        target = self.state.get("duration", 0)
        note = "" if typed == target else " — khi duyệt sẽ tự chia lại cho khớp"
        self.outline_total.setText(f"Tổng: {typed} giây / mục tiêu {target} giây{note}")

    def _write_script(self) -> None:
        duration = self.state["duration"]
        points = steps.parse_outline_text(self.outline_edit.toPlainText(), duration)
        title = self.outline_title.text().strip() or self.state["topic"]
        if len(points) < 2:
            QMessageBox.information(self, "Đề cương quá ngắn", "Đề cương cần ít nhất 2 ý.")
            return
        self.state["outline"] = {"title": title, "points": points, "approved": True}
        self._save()
        self.outline_edit.setPlainText(steps.outline_to_text(points))
        state = dict(self.state)
        voice = next(iter(catalog.VOICES))

        def write_and_fit(provider):
            script = steps.write_script(provider, state["content_type"], state["category"], state["topic"], title, points)
            return steps.fit_script_duration(provider, state["content_type"], state["category"], script,
                                             duration, voice, provider.notify)

        self._run("AI đang viết kịch bản và canh thời lượng...", self._ai_job(write_and_fit), self._show_script)

    # ---------- step 4: script ----------

    def _build_script(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_heading("Kịch bản"))
        layout.addWidget(_hint("Kiểm tra kỹ năm tháng, tên người, địa danh. AI có thể viết sai với nội dung lịch sử."))
        self.script_title = QLineEdit()
        self.script_hook = QPlainTextEdit()
        self.script_hook.setFixedHeight(70)
        self.script_body = QPlainTextEdit()
        self.script_stats = QLabel()
        for widget in (self.script_hook, self.script_body):
            widget.textChanged.connect(self._update_script_stats)
        layout.addWidget(QLabel("Tiêu đề"))
        layout.addWidget(self.script_title)
        layout.addWidget(QLabel("Hook (câu mở đầu)"))
        layout.addWidget(self.script_hook)
        layout.addWidget(QLabel("Thân bài"))
        layout.addWidget(self.script_body, 1)
        layout.addWidget(self.script_stats)
        again = QPushButton("Viết lại")
        measure = QPushButton("Đo lại thời lượng")
        approve = _primary("Duyệt → Chia cảnh")
        again.clicked.connect(self._write_script)
        measure.clicked.connect(self._remeasure_script)
        approve.clicked.connect(self._split_scenes)
        layout.addLayout(_buttons(again, measure, approve))
        return page

    def _script_from_editor(self) -> dict:
        return {"title": self.script_title.text().strip(), "hook": self.script_hook.toPlainText().strip(),
                "body": self.script_body.toPlainText().strip()}

    def _remeasure_script(self) -> None:
        """Keep the user's wording: only the speaking rate is tuned (no AI rewrite)."""
        script = self._script_from_editor()
        if not script["hook"] or not script["body"]:
            return
        duration, voice = self.state["duration"], next(iter(catalog.VOICES))

        def job(progress):
            return steps.fit_script_duration(None, "", "", script, duration, voice, progress)

        def done(fitted):
            self.state["script"] = {**self.state.get("script", {}), **fitted}
            self._save()
            self._update_script_stats()

        self._run("Đo thời lượng giọng đọc", job, done)

    def _show_script(self, script: dict) -> None:
        self.state["script"] = script
        self._save()
        self.script_title.setText(script["title"])
        self.script_hook.setPlainText(script["hook"])
        self.script_body.setPlainText(script["body"])
        self._reset_from(3)

    def _update_script_stats(self) -> None:
        hook, body = self.script_hook.toPlainText(), self.script_body.toPlainText()
        words = steps.word_count(hook) + steps.word_count(body)
        target = self.state.get("duration", 0)
        fitted = (self.state.get("script") or {}).get("timing")
        if fitted and fitted.get("narration") == timing.narration({"hook": hook, "body": body}):
            status = "khớp" if fitted["within_tolerance"] else f"lệch quá {timing.TOLERANCE_SECONDS:.0f}s, nên Viết lại"
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
                                                                   script["body"], duration)),
                  self._show_scenes)

    # ---------- step 5: scenes and images ----------

    def _build_scenes(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_heading("Cảnh & ảnh"))
        layout.addWidget(_hint("Tự động, ưu tiên từ khóa của từng cảnh: Commons (từ khóa Việt, Anh) → Wikipedia tiếng Việt "
                               "→ Openverse → ảnh chung của chủ đề → Pollinations (nếu bật) → ảnh thay thế. "
                               "Ảnh AI chỉ là minh họa, không phải tư liệu thật. Nút Gemini cần API key có billing."))
        self.pollinations_check = QCheckBox("Dùng ảnh AI miễn phí (Pollinations) khi không tìm được ảnh thật")
        self.pollinations_check.setChecked(True)
        layout.addWidget(self.pollinations_check)
        body = QHBoxLayout()
        self.scene_list = QListWidget()
        self.scene_list.setIconSize(QSize(72, 128))
        self.scene_list.setWordWrap(True)
        self.scene_list.currentRowChanged.connect(self._show_scene_detail)
        body.addWidget(self.scene_list, 3)
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
        other = QPushButton("Ảnh Wikimedia khác")
        pollinations = QPushButton("Ảnh AI (Pollinations)")
        ai = QPushButton("Ảnh AI (Gemini)")
        other.clicked.connect(self._next_wikimedia)
        pollinations.clicked.connect(self._pollinations_image)
        ai.clicked.connect(self._ai_image)
        detail.addWidget(self.scene_preview, 0, Qt.AlignHCenter)
        detail.addWidget(self.scene_text)
        detail.addWidget(self.scene_query_vi)
        detail.addWidget(self.scene_query)
        detail.addWidget(self.scene_credit)
        detail.addLayout(_buttons(other))
        detail.addLayout(_buttons(pollinations, ai))
        detail.addStretch(1)
        body.addLayout(detail, 2)
        layout.addLayout(body, 1)
        resplit = QPushButton("Chia cảnh lại")
        fetch = QPushButton("Tìm lại ảnh (cảnh thiếu / ảnh thay thế)")
        next_button = _primary("Tiếp tục → Render")
        resplit.clicked.connect(self._split_scenes)
        fetch.clicked.connect(self._fetch_missing_images)
        next_button.clicked.connect(self._to_render)
        layout.addLayout(_buttons(resplit, fetch, next_button))
        return page

    def _show_scenes(self, result: dict) -> None:
        self.state["image_subject"] = result["subject"]
        self.state["scenes"] = result["scenes"]
        self._save()
        self._refresh_scene_list()
        self._reset_from(4)
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
            credit = image.get("credit", "")
            self.scene_credit.setText(f"Nguồn: {credit}\n{image.get('page', '')}".strip())
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
        if errors:
            QMessageBox.warning(self, "Một số cảnh chưa có ảnh", "\n".join(errors))

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
        self._go(5)

    # ---------- step 6: render ----------

    def _fill_templates(self, content_type: str) -> None:
        """Only templates of the current content type are offered (history styles are separate from news)."""
        current = self.template_combo.currentData()
        self.template_combo.clear()
        for key, label in catalog.TEMPLATES_BY_TYPE.get(content_type, catalog.NEWS_TEMPLATES).items():
            self.template_combo.addItem(label, key)
        index = self.template_combo.findData(current)
        self.template_combo.setCurrentIndex(max(0, index))

    def _build_render(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_heading("Render video"))
        form = QFormLayout()
        self.voice_combo = QComboBox()
        for key, label in catalog.VOICES.items():
            self.voice_combo.addItem(label, key)
        self.template_combo = QComboBox()
        self._fill_templates("kien_thuc")
        self.resolution_combo = QComboBox()
        for value in catalog.RESOLUTIONS:
            self.resolution_combo.addItem(value, value)
        self.music_edit = QLineEdit()
        self.music_edit.setReadOnly(True)
        self.music_edit.setPlaceholderText("Không dùng nhạc nền")
        browse = QPushButton("Chọn...")
        clear = QPushButton("Bỏ")
        browse.clicked.connect(self._choose_music)
        clear.clicked.connect(self.music_edit.clear)
        music_row = QHBoxLayout()
        music_row.addWidget(self.music_edit, 1)
        music_row.addWidget(browse)
        music_row.addWidget(clear)
        self.volume_spin = QSpinBox()
        self.volume_spin.setRange(0, 100)
        self.volume_spin.setValue(15)
        self.volume_spin.setSuffix(" %")
        form.addRow("Giọng đọc", self.voice_combo)
        form.addRow("Template", self.template_combo)
        form.addRow("Độ phân giải", self.resolution_combo)
        form.addRow("Nhạc nền", music_row)
        form.addRow("Âm lượng nhạc", self.volume_spin)
        layout.addLayout(form)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.result_label)
        layout.addStretch(1)
        self.open_video = QPushButton("Mở video")
        self.open_folder = QPushButton("Mở thư mục")
        render_button = _primary("Render video")
        self.open_video.clicked.connect(lambda: self._open(self.state.get("video")))
        self.open_folder.clicked.connect(lambda: self._open(str(self.store.directory) if self.store else None))
        render_button.clicked.connect(self._render)
        self.open_video.setEnabled(False)
        layout.addLayout(_buttons(self.open_folder, self.open_video, render_button))
        return page

    def _choose_music(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn nhạc nền", "", "Audio (*.mp3 *.wav *.m4a)")
        if path:
            self.music_edit.setText(path)

    def _render(self) -> None:
        options = {"voice": self.voice_combo.currentData(), "template": self.template_combo.currentData(),
                   "resolution": self.resolution_combo.currentData(), "music_volume": self.volume_spin.value(),
                   "music_source": self.music_edit.text()}
        self.state["render"] = options
        self._save()
        store, state = self.store, self.state
        self.open_video.setEnabled(False)
        self.result_label.setText("")

        def job(progress):
            # Re-fit against the voice actually chosen for rendering (speaking speed differs per voice).
            script = state["script"]
            fitted = script.get("timing") or {}
            if fitted.get("voice") != options["voice"] or fitted.get("narration") != timing.narration(script):
                fitted = timing.fit_rate(timing.narration(script), options["voice"], state["duration"], progress)
                script["timing"] = fitted
            snapshot = build_snapshot(state, options, import_music(store, options["music_source"]), fitted["tts_rate"])
            return str(render_video(store, snapshot, progress))

        def done(video_path):
            self.state["video"] = video_path
            self._save()
            self.result_label.setText(f"Video: {video_path}")
            self.open_video.setEnabled(True)

        self._run("Render video", job, done)

    def _open(self, path: str | None) -> None:
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
