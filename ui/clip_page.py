"""Step 4 of the clip flow: pick one source video, match its shots to the scenes and review every scene."""
import html
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from core import clips, images
from ui import icons
from ui.widgets import Card, label

PREVIEW_W, PREVIEW_H = 270, 480


def _button(text: str, name: str = "", icon: str | None = None, color: str = "#334155") -> QPushButton:
    button = QPushButton(text)
    if name:
        button.setObjectName(name)
    if icon:
        button.setIcon(icons.icon(icon, color, 16))
        button.setIconSize(QSize(16, 16))
    button.setCursor(Qt.PointingHandCursor)
    return button


def _row(*widgets, stretch_first: bool = False) -> QHBoxLayout:
    row = QHBoxLayout()
    if not stretch_first:
        row.addStretch(1)
    for index, widget in enumerate(widgets):
        row.addWidget(widget, 1 if stretch_first and index == 0 else 0)
    return row


def _clock(seconds: float) -> str:
    seconds = max(0, round(seconds))
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60}:{seconds % 60:02d}"


class _LogoCanvas(QLabel):
    """A video frame on which logo regions are drawn by dragging; regions are kept as fractions of the frame."""

    def __init__(self, pixmap: QPixmap, logos: list[list[float]]):
        super().__init__()
        self.base = pixmap.scaled(720, 405, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setFixedSize(self.base.size())
        self.logos = [list(box) for box in logos]
        self.start: QPoint | None = None
        self.current: QRect | None = None
        self.setCursor(Qt.CrossCursor)
        self._paint()

    def _paint(self) -> None:
        canvas = QPixmap(self.base)
        painter = QPainter(canvas)
        painter.setPen(QPen(QColor("#ef4444"), 2))
        painter.setBrush(QBrush(QColor(239, 68, 68, 70)))
        width, height = canvas.width(), canvas.height()
        for x, y, w, h in self.logos:
            painter.drawRect(QRect(round(x * width), round(y * height), round(w * width), round(h * height)))
        if self.current:
            painter.drawRect(self.current)
        painter.end()
        self.setPixmap(canvas)

    def mousePressEvent(self, event):
        self.start = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.current = QRect(self.start, event.position().toPoint()).normalized()
            self._paint()

    def mouseReleaseEvent(self, event):
        if self.current and self.current.width() > 4 and self.current.height() > 4:
            rect = self.current.intersected(self.rect())
            width, height = self.width(), self.height()
            self.logos.append([round(rect.x() / width, 4), round(rect.y() / height, 4),
                               round(rect.width() / width, 4), round(rect.height() / height, 4)])
        self.start, self.current = None, None
        self._paint()

    def clear(self) -> None:
        self.logos = []
        self._paint()


class ClipPage(QWidget):
    """Runs its jobs through the main window (busy state, progress, AI provider) and edits its state."""

    def __init__(self, window):
        super().__init__()
        self.window = window

        source = Card("Video nguồn", "Cả video dùng các shot của 1 video nguồn nên màu và chất hình đồng đều. "
                      "Tự tìm video Creative Commons (được phép dùng lại, phải ghi nguồn) theo từ khóa chủ đề, "
                      "hoặc dán link YouTube bạn có quyền dùng.", "film")
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Từ khóa chủ đề, ví dụ: Điện Biên Phủ 1954")
        self.filter_combo = QComboBox()
        for key, (name, _kinds) in clips.CONTENT_FILTERS.items():
            self.filter_combo.addItem(name, key)
        self.filter_combo.setToolTip("Chỉ tư liệu thật: bỏ video hoạt hình, 3D, slide, tranh vẽ. "
                                     "Cho phép hoạt hình: vẫn bỏ slide và slideshow ảnh tĩnh.")
        search = _button("Tìm video", "soft", "search", "#1d4ed8")
        search.clicked.connect(self._search)
        search_row = QHBoxLayout()
        search_row.addWidget(self.query_edit, 1)
        search_row.addWidget(self.filter_combo)
        search_row.addWidget(search)
        source.body.addLayout(search_row)
        source.body.addWidget(label("Tìm khoảng 8 video, AI xem thử từng video (mỗi video ~20 giây). Video có logo "
                                    "vẫn dùng được: logo được crop ra ngoài khung dọc hoặc làm mờ.", "hint", wrap=True))
        self.candidate_list = QListWidget()
        self.candidate_list.setIconSize(QSize(120, 135))
        self.candidate_list.setWordWrap(True)
        self.candidate_list.setMinimumHeight(200)
        self.candidate_list.itemDoubleClicked.connect(lambda _item: self._use_selected())
        source.body.addWidget(self.candidate_list)
        use = QPushButton("Dùng video đã chọn")
        use.setObjectName("primary")
        use.setCursor(Qt.PointingHandCursor)
        use.clicked.connect(self._use_selected)
        source.body.addLayout(_row(use))
        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText("Hoặc dán link YouTube (video của bạn / video bạn có quyền dùng)")
        use_link = _button("Dùng link này", icon="plus")
        use_link.clicked.connect(self._use_link)
        source.body.addLayout(_row(self.link_edit, use_link, stretch_first=True))
        self.source_info = label("", "hint", wrap=True)
        self.source_info.setTextFormat(Qt.RichText)
        self.source_info.setOpenExternalLinks(True)
        source.body.addWidget(self.source_info)
        self.logo_info = label("", "hint", wrap=True)
        mark = _button("Khoanh vùng logo...", icon="edit")
        mark.clicked.connect(self._mark_logos)
        no_logo = _button("Không có logo")
        no_logo.clicked.connect(self._clear_logos)
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_info, 1)
        logo_row.addWidget(mark)
        logo_row.addWidget(no_logo)
        self.logo_widgets = [mark, no_logo]
        source.body.addLayout(logo_row)

        scenes = Card("Cảnh & clip", "AI ghép mỗi cảnh với 1 shot của video nguồn. Khung xem trước là phần 9:16 sẽ "
                      "dùng; ô đỏ là logo sẽ được làm mờ.", "image")
        body = QHBoxLayout()
        body.setSpacing(16)
        self.scene_list = QListWidget()
        self.scene_list.setIconSize(QSize(72, 128))
        self.scene_list.setWordWrap(True)
        self.scene_list.setMinimumHeight(520)
        self.scene_list.currentRowChanged.connect(self._show_detail)
        body.addWidget(self.scene_list, 1)
        detail = QVBoxLayout()
        self.preview = QLabel("Chưa có clip")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.scene_text = label("", "", wrap=True)
        self.shot_info = label("", "hint", wrap=True)
        pick = _button("Chọn shot khác...", icon="film")
        pick.clicked.connect(self._pick_shot)
        picture = _button("Dùng ảnh thay", icon="image")
        picture.setToolTip("Cảnh này dùng ảnh tư liệu (tìm như luồng ảnh) thay cho clip.")
        picture.clicked.connect(self._use_picture)
        detail.addWidget(self.preview, 0, Qt.AlignHCenter)
        detail.addWidget(self.scene_text)
        detail.addWidget(self.shot_info)
        detail.addLayout(_row(pick, picture))
        detail.addStretch(1)
        # Fixed width, as on the picture step: long text must not squeeze the scene list.
        panel = QWidget()
        panel.setFixedWidth(320)
        panel.setLayout(detail)
        body.addWidget(panel)
        scenes.body.addLayout(body)
        resplit = _button("Chia cảnh lại", icon="refresh")
        resplit.clicked.connect(self.window._split_scenes)
        reassign = _button("Ghép lại tự động", icon="sparkles")
        reassign.setToolTip("AI ghép lại shot cho mọi cảnh (bỏ các lựa chọn tay).")
        reassign.clicked.connect(self.reassign)
        next_button = QPushButton("Tiếp tục → Chọn mẫu")
        next_button.setObjectName("primary")
        next_button.setCursor(Qt.PointingHandCursor)
        next_button.clicked.connect(self.window._to_render)
        scenes.body.addLayout(_row(resplit, reassign, next_button))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(source)
        layout.addWidget(scenes)

    # ---------- state helpers ----------

    @property
    def state(self) -> dict:
        return self.window.state

    def _shots_dir(self) -> Path:
        return self.window.store.assets / "clip_shots"

    def _source(self) -> dict | None:
        return self.state.get("clip_source")

    def reset(self) -> None:
        for widget in (self.query_edit, self.link_edit):
            widget.clear()
        self.candidate_list.clear()
        self.scene_list.clear()
        for widget in (self.source_info, self.logo_info, self.scene_text, self.shot_info):
            widget.setText("")
        self.preview.clear()
        self.preview.setText("Chưa có clip")

    def load(self) -> None:
        """Show the saved state of this run (after opening it or after the scenes were split)."""
        subject = self.state.get("image_subject") or {}
        self.query_edit.setText(self.state.get("clip_query") or subject.get("vi") or self.state.get("topic", ""))
        self.filter_combo.setCurrentIndex(max(0, self.filter_combo.findData(self.state.get("clip_filter"))))
        self._fill_candidates()
        self._show_source()
        self.refresh_scenes()

    def scenes_ready(self) -> None:
        """New scenes from the AI split or a JSON import: match them to the source video if one is chosen."""
        self.load()
        link = self.state.get("clip_link", "")
        if self._source():
            self.reassign()
        elif link:
            # Link given in step 1: use it straight away (it was validated there).
            self.link_edit.setText(link)
            self._prepare(clips.youtube_id(link))
        else:
            self.window.status.setText("Tìm hoặc dán link video nguồn để ghép clip cho các cảnh.")

    # ---------- source video ----------

    def _search(self) -> None:
        query = self.query_edit.text().strip()
        if len(query) < 2:
            QMessageBox.information(self, "Thiếu từ khóa", "Nhập từ khóa chủ đề để tìm video.")
            return
        content_filter = self.filter_combo.currentData()
        self.state.update({"clip_query": query, "clip_filter": content_filter})

        def done(candidates: list[dict]) -> None:
            self.state["clip_candidates"] = candidates
            self.window._save()
            self._fill_candidates()
            if not candidates:
                QMessageBox.information(self, "Không có video phù hợp",
                                        "Không tìm được video Creative Commons dùng được. Thử từ khóa ngắn hơn, "
                                        "tiếng Anh, hoặc dán link video bạn có quyền dùng.")

        self.window._run("Tìm video nguồn Creative Commons...",
                         lambda progress: clips.find_candidates(query, content_filter, progress), done)

    def _fill_candidates(self) -> None:
        self.candidate_list.clear()
        for candidate in self.state.get("clip_candidates") or []:
            kind = clips.KIND_LABELS.get(candidate.get("kind"), "?")
            logo = "có logo" if candidate.get("watermark") else "không thấy logo"
            lines = [candidate["title"], f"{candidate['channel']} · {_clock(candidate['duration'])} ·  BY",
                     f"AI xem: {kind}, {logo}"]
            if not candidate.get("allowed"):
                lines.append("Không hợp bộ lọc loại nguồn")
            item = QListWidgetItem("\n".join(lines))
            item.setData(Qt.UserRole, candidate["id"])
            board = Path(candidate.get("board") or "")
            if board.is_file():
                item.setIcon(QIcon(QPixmap(str(board))))
            if not candidate.get("allowed"):
                item.setForeground(QColor("#94a3b8"))
            self.candidate_list.addItem(item)

    def _use_selected(self) -> None:
        item = self.candidate_list.currentItem()
        if not item:
            QMessageBox.information(self, "Chưa chọn video", "Chọn 1 video trong danh sách.")
            return
        self._prepare(item.data(Qt.UserRole))

    def _use_link(self) -> None:
        try:
            video_id = clips.youtube_id(self.link_edit.text())
        except clips.ClipError as error:
            QMessageBox.information(self, "Link chưa đúng", str(error))
            return
        self._prepare(video_id)

    def _prepare(self, video_id: str) -> None:
        if not self.state.get("scenes"):
            QMessageBox.information(self, "Chưa có cảnh", "Hãy chia cảnh kịch bản trước.")
            return
        scenes, total, thumbs = self.state["scenes"], clips.estimated_total(self.state), self._shots_dir()

        def call(provider):
            source = clips.prepare_source(video_id, thumbs, provider.notify)
            clips.describe_shots(source, thumbs, provider.notify)
            provider.notify("AI ghép shot với cảnh", -1)
            chosen, warnings = clips.assign_shots(provider, scenes, source["shots"], total)
            return source, chosen, warnings

        def done(result) -> None:
            source, chosen, warnings = result
            self.state["clip_source"] = source
            self._apply(chosen)
            self._show_source()
            self._fill_pictures(warnings)

        self.window._run("Chuẩn bị video nguồn (tải 360p, tách shot, AI xem)...", self.window._ai_job(call), done)

    def _show_source(self) -> None:
        source = self._source()
        for widget in self.logo_widgets:
            widget.setEnabled(bool(source))
        if not source:
            self.source_info.setText("Chưa chọn video nguồn.")
            self.logo_info.setText("")
            return
        license_text = "CC BY (ghi nguồn khi đăng)" if clips.is_creative_commons(source.get("license", "")) \
            else "Không rõ giấy phép — chỉ dùng video bạn có quyền dùng"
        self.source_info.setText(
            f"<b>{html.escape(source['title'])}</b><br>{html.escape(source['channel'])} · {_clock(source['duration'])} · "
            f"{len(source['shots'])} shot · {license_text} · "
            f"<a href=\"{html.escape(source['url'], quote=True)}\">Mở trên YouTube</a>")
        logos = source.get("logos") or []
        origin = "tự dò" if source.get("logos_from") == "auto" else "bạn khoanh"
        self.logo_info.setText(f"Logo: {len(logos)} vùng ({origin}) — crop dọc tránh logo, vùng còn trong khung "
                               "sẽ làm mờ." if logos else "Logo: không thấy logo nào.")

    def _mark_logos(self) -> None:
        source = self._source()
        if not source:
            return
        shots = source["shots"]
        row = self.scene_list.currentRow()
        clip = (self.state["scenes"][row].get("clip") or {}) if 0 <= row < len(self.state.get("scenes") or []) else {}
        thumb = clip.get("thumb") or shots[len(shots) // 2]["thumb"]
        pixmap = QPixmap(str(self._shots_dir() / thumb))
        if pixmap.isNull():
            QMessageBox.information(self, "Thiếu ảnh", "Không đọc được khung hình của shot.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Khoanh vùng logo")
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Kéo chuột để khoanh từng logo/chữ của kênh. Vùng khoanh áp dụng cho cả video: "
                               "khung dọc sẽ tránh vùng đó, không tránh được thì làm mờ.", "hint", wrap=True))
        canvas = _LogoCanvas(pixmap, source.get("logos") or [])
        layout.addWidget(canvas)
        clear, cancel, save = _button("Xóa hết"), _button("Hủy"), QPushButton("Lưu")
        save.setObjectName("primary")
        clear.clicked.connect(canvas.clear)
        cancel.clicked.connect(dialog.reject)
        save.clicked.connect(dialog.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(clear)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        if dialog.exec() == QDialog.Accepted:
            source.update({"logos": canvas.logos, "logos_from": "manual"})
            self.window._save()
            self._show_source()
            self._show_detail(self.scene_list.currentRow())

    def _clear_logos(self) -> None:
        source = self._source()
        if source:
            source.update({"logos": [], "logos_from": "manual"})
            self.window._save()
            self._show_source()
            self._show_detail(self.scene_list.currentRow())

    # ---------- scenes ----------

    def _apply(self, chosen: list[int | None]) -> None:
        shots = self._source()["shots"]
        for scene, shot in zip(self.state["scenes"], chosen):
            scene["clip"] = {"shot": shot, "thumb": shots[shot]["thumb"]} if shot is not None else None
        self.window._save()
        self.refresh_scenes(self.scene_list.currentRow())

    def reassign(self) -> None:
        source = self._source()
        if not source:
            QMessageBox.information(self, "Chưa có video nguồn", "Chọn video nguồn trước.")
            return
        scenes, total = self.state["scenes"], clips.estimated_total(self.state)

        def done(result) -> None:
            chosen, warnings = result
            self._apply(chosen)
            self._fill_pictures(warnings)

        self.window._run("AI ghép shot với cảnh...",
                         self.window._ai_job(lambda provider: clips.assign_shots(provider, scenes, source["shots"], total)),
                         done)

    def _fill_pictures(self, notes: list[str]) -> None:
        """Scenes left without a shot get a picture, searched the same way as in the picture flow."""
        scenes = self.state["scenes"]
        todo = [index for index, scene in enumerate(scenes) if not scene.get("clip") and not scene.get("image")]
        if not todo:
            if notes:
                QMessageBox.warning(self, "Cần kiểm tra một số cảnh", "\n".join(notes))
            return
        store, topic = self.window.store, self.state.get("topic", "")
        title = (self.state.get("script") or {}).get("title", topic)
        subject = self.state.get("image_subject") or {}

        def job(progress):
            errors = []
            for number, index in enumerate(todo, 1):
                progress(f"Tìm ảnh thay cho cảnh {index + 1}", round(100 * (number - 1) / len(todo)))
                used = {(scene.get("image") or {}).get("url") for scene in scenes} - {None}
                try:
                    scenes[index]["image"], warnings = images.fetch_scene_image(
                        scenes[index], store.assets, index, used, topic, title, [], False, subject)
                    errors.extend(warnings)
                except images.ImageError as error:
                    errors.append(str(error))
            return errors

        def done(errors: list[str]) -> None:
            self.window._save()
            self.refresh_scenes(self.scene_list.currentRow())
            if notes or errors:
                QMessageBox.warning(self, "Cần kiểm tra một số cảnh", "\n".join(notes + errors))

        self.window._run("Tìm ảnh cho cảnh không có shot hợp", job, done)

    def _scene_pixmap(self, scene: dict) -> QPixmap | None:
        clip = scene.get("clip")
        if clip:
            return QPixmap(str(self._shots_dir() / clip["thumb"]))
        if scene.get("image"):
            return QPixmap(str(self.window.store.assets / scene["image"]["file"]))
        return None

    def _vertical_frame(self, frame: QPixmap) -> QPixmap:
        """The 9:16 part of a shot frame the render will use, with blurred logo areas outlined in red."""
        source = self._source() or {}
        (x, y, w, h), blurs = clips.crop_plan(frame.width(), frame.height(), 1080, 1920, source.get("logos") or [])
        vertical = frame.copy(x, y, w, h).scaled(PREVIEW_W, PREVIEW_H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if blurs:
            painter = QPainter(vertical)
            painter.setPen(QPen(QColor("#ef4444"), 2))
            painter.setBrush(QBrush(QColor(239, 68, 68, 90)))
            scale_x, scale_y = PREVIEW_W / w, PREVIEW_H / h
            for bx, by, bw, bh in blurs:
                painter.drawRect(QRect(round(bx * scale_x), round(by * scale_y), round(bw * scale_x), round(bh * scale_y)))
            painter.end()
        return vertical

    def refresh_scenes(self, select: int = 0) -> None:
        self.scene_list.blockSignals(True)
        self.scene_list.clear()
        source = self._source()
        for index, scene in enumerate(self.state.get("scenes") or []):
            clip = scene.get("clip")
            if clip and source:
                tag = f"Shot {clip['shot'] + 1}"
            elif scene.get("image"):
                tag = "Ảnh thay"
            else:
                tag = "chưa có clip"
            item = QListWidgetItem(f"Cảnh {index + 1} [{tag}]\n{scene['text'][:140]}")
            pixmap = self._scene_pixmap(scene)
            if pixmap and not pixmap.isNull():
                item.setIcon(QIcon(self._vertical_frame(pixmap) if clip else pixmap))
            self.scene_list.addItem(item)
        self.scene_list.blockSignals(False)
        if self.scene_list.count():
            self.scene_list.setCurrentRow(min(max(0, select), self.scene_list.count() - 1))
            self._show_detail(self.scene_list.currentRow())

    def _show_detail(self, row: int) -> None:
        scenes = self.state.get("scenes") or []
        if not 0 <= row < len(scenes):
            return
        scene, source = scenes[row], self._source()
        self.scene_text.setText(scene["text"])
        pixmap = self._scene_pixmap(scene)
        clip = scene.get("clip")
        if pixmap is None or pixmap.isNull():
            self.preview.clear()
            self.preview.setText("Chưa có clip")
        elif clip:
            self.preview.setPixmap(self._vertical_frame(pixmap))
        else:
            self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if clip and source:
            shot = source["shots"][clip["shot"]]
            length = shot["end"] - shot["start"]
            need = clips.scene_seconds(scenes, clips.estimated_total(self.state))[row]
            note = ""
            if need > length * clips.MAX_SLOWDOWN:
                note = "\nShot ngắn hơn cảnh nhiều: sẽ phát chậm rồi lặp lại — nên chọn shot dài hơn."
            elif need > length:
                note = "\nShot hơi ngắn: sẽ phát chậm lại một chút."
            self.shot_info.setText(f"Shot {clip['shot'] + 1}/{len(source['shots'])} · {_clock(shot['start'])}–"
                                   f"{_clock(shot['end'])} ({length:.1f}s; cảnh cần ~{need:.0f}s)\n"
                                   f"{shot.get('desc') or ''}{note}")
        elif scene.get("image"):
            self.shot_info.setText(f"Dùng ảnh: {scene['image'].get('credit', '')}")
        else:
            self.shot_info.setText("")

    def _pick_shot(self) -> None:
        row, source = self.scene_list.currentRow(), self._source()
        if row < 0 or not source:
            return
        scenes = self.state["scenes"]
        owner = {scene["clip"]["shot"]: index for index, scene in enumerate(scenes) if scene.get("clip")}
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Chọn shot cho cảnh {row + 1}")
        dialog.resize(900, 640)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(scenes[row]["text"], "hint", wrap=True))
        grid = QListWidget()
        grid.setViewMode(QListView.IconMode)
        grid.setIconSize(QSize(192, 108))
        grid.setGridSize(QSize(210, 170))
        grid.setResizeMode(QListView.Adjust)
        grid.setMovement(QListView.Static)
        grid.setWordWrap(True)
        for index, shot in enumerate(source["shots"]):
            used = f" · cảnh {owner[index] + 1}" if index in owner else ""
            item = QListWidgetItem(QIcon(QPixmap(str(self._shots_dir() / shot["thumb"]))),
                                   f"{index + 1}. {_clock(shot['start'])} ({shot['end'] - shot['start']:.1f}s){used}")
            item.setToolTip(shot.get("desc") or "")
            grid.addItem(item)
        current = (scenes[row].get("clip") or {}).get("shot")
        if current is not None:
            grid.setCurrentRow(current)
        layout.addWidget(grid, 1)
        layout.addWidget(label("Shot đang dùng ở cảnh khác sẽ được đổi chỗ với cảnh này.", "hint"))
        cancel, choose = _button("Hủy"), QPushButton("Chọn shot")
        choose.setObjectName("primary")
        cancel.clicked.connect(dialog.reject)
        choose.clicked.connect(dialog.accept)
        grid.itemDoubleClicked.connect(lambda _item: dialog.accept())
        layout.addLayout(_row(cancel, choose))
        if dialog.exec() != QDialog.Accepted or grid.currentRow() < 0:
            return
        picked = grid.currentRow()
        other = owner.get(picked)
        if other is not None and other != row:
            previous = scenes[row].get("clip")
            scenes[other]["clip"] = {"shot": previous["shot"], "thumb": previous["thumb"]} if previous else None
        scenes[row]["clip"] = {"shot": picked, "thumb": source["shots"][picked]["thumb"]}
        self.window._save()
        self.refresh_scenes(row)

    def _use_picture(self) -> None:
        row = self.scene_list.currentRow()
        scenes = self.state.get("scenes") or []
        if not 0 <= row < len(scenes):
            return
        scenes[row]["clip"] = None
        if scenes[row].get("image"):
            self.window._save()
            self.refresh_scenes(row)
            return
        self._fill_pictures([])
