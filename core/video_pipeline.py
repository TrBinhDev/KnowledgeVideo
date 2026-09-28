import asyncio
import html
import json
import logging
import os
import re
import shutil
import subprocess
import textwrap
import threading
from pathlib import Path
from urllib.parse import urlparse

import edge_tts
from edge_tts.exceptions import NoAudioReceived

from core.catalog import TRANSITIONS, WORDS_PER_SECOND
from core.network_security import fetch_safe_bytes
from core.title_cards import HISTORY_GRADES, HISTORY_TEMPLATES, HISTORY_TRANSITIONS, render_title_card

logger = logging.getLogger("kv.pipeline")


_VECTOR_TEMPLATE_FILES = {
    "banner-yellow": "banner_yellow.svg",
    "banner-red": "banner_red.svg",
    "banner-neon": "banner_neon.svg",
}
_VIDEO_FPS = 30
_MAX_ARTICLE_IMAGES = 16
_TTS_ATTEMPTS = 3
TRANSITION_SECONDS = 0.6
_qt_application = None


def transition_names(template: str, choice: str, cuts: int) -> list[str]:
    """xfade transition name for each cut between scenes ("none" = hard cut)."""
    if choice not in TRANSITIONS:
        raise RuntimeError("Kiểu chuyển cảnh không hợp lệ.")
    if choice == "none":
        return ["none"] * cuts
    cycle = HISTORY_TRANSITIONS.get(template, ("fade",)) if choice == "template" else (choice,)
    return [cycle[index % len(cycle)] for index in range(cuts)]


def transition_seconds(scene_duration: float, names: list[str]) -> float:
    if not names or names[0] == "none":
        return 0.0
    return min(TRANSITION_SECONDS, scene_duration * 0.20)


def scene_look(width: int, height: int, grade: str) -> str:
    """Per-scene filter shared by the render and the preview: fill the frame, darken slightly for text, grade."""
    return (
        f"fps={_VIDEO_FPS},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
        f"eq=brightness=-0.04:saturation=0.98,{grade}"
    )


def join_scenes(count: int, starts: list[float], names: list[str], overlap: float) -> list[str]:
    """Filters joining [scene0]..[scene{count-1}] into [joined].

    Every scene except the last must run `overlap` seconds past the next scene's start: scene i then begins
    exactly at starts[i], in step with the narration.
    """
    if count == 1:
        return ["[scene0]null[joined]"]
    if not overlap:
        return ["".join(f"[scene{index}]" for index in range(count)) + f"concat=n={count}:v=1:a=0[joined]"]
    filters, previous = [], "scene0"
    for index in range(1, count):
        label = "joined" if index == count - 1 else f"transition{index}"
        filters.append(
            f"[{previous}][scene{index}]xfade=transition={names[index - 1]}:"
            f"duration={overlap:.3f}:offset={starts[index]:.3f}[{label}]"
        )
        previous = label
    return filters


def _rasterize_vector_template(template: str, width: int, directory: Path):
    filename = _VECTOR_TEMPLATE_FILES.get(template)
    if not filename:
        return None
    source = Path(__file__).resolve().parents[1] / "assets" / "templates" / filename
    if not source.is_file():
        raise RuntimeError(f"Thiếu artwork template: {filename}.")
    try:
        from PySide6.QtGui import QGuiApplication, QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
    except ImportError as error:
        raise RuntimeError("Thiếu QtSvg để rasterize artwork template.") from error

    global _qt_application
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _qt_application = QGuiApplication([])
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise RuntimeError(f"Artwork template không hợp lệ: {filename}.")
    default_size = renderer.defaultSize()
    raster_height = max(1, round(width * default_size.height() / default_size.width()))
    image = QImage(width, raster_height, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    output = directory / "template_artwork.png"
    if not image.save(str(output), "PNG"):
        raise RuntimeError("Không thể tạo ảnh tạm từ artwork template.")
    return output, raster_height


class RenderCancelled(RuntimeError):
    """The user cancelled the render."""


# Media processes per worker thread, so cancelling a render leaves previews running in other threads alone.
_processes: dict[int, set] = {}
_cancelled: set[int] = set()
_process_lock = threading.Lock()


def cancel_thread(thread_id: int) -> None:
    """Stop the media work of one worker thread: kill its running ffmpeg and refuse to start new ones."""
    with _process_lock:
        _cancelled.add(thread_id)
        processes = list(_processes.get(thread_id, ()))
    for process in processes:
        _kill_tree(process)


def _kill_tree(process: subprocess.Popen) -> None:
    # "ffmpeg" on PATH may be a launcher shim (e.g. Chocolatey) whose child is the real encoder, and killing only
    # the shim leaves that child running; taskkill /T ends the whole tree.
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    process.kill()


def clear_cancel(thread_id: int) -> None:
    with _process_lock:
        _cancelled.discard(thread_id)


def check_cancelled() -> None:
    if threading.get_ident() in _cancelled:
        raise RenderCancelled("Đã hủy render.")


def _start(arguments, **options) -> subprocess.Popen:
    thread_id = threading.get_ident()
    with _process_lock:
        if thread_id in _cancelled:
            raise RenderCancelled("Đã hủy render.")
        process = subprocess.Popen(arguments, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                   **options)
        _processes.setdefault(thread_id, set()).add(process)
    return process


def _release(process: subprocess.Popen) -> None:
    with _process_lock:
        _processes.get(threading.get_ident(), set()).discard(process)


def render_motion_scene(source: Path, output: Path, width: int, height: int,
                        duration: float, direction: int) -> None:
    """Ken Burns clip of one still image: slow zoom and pan, drawn frame by frame with Qt and encoded by ffmpeg."""
    try:
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QGuiApplication, QImage, QPainter
    except ImportError as error:
        raise RuntimeError("Thiếu PySide6 để render chuyển động Ken Burns.") from error

    global _qt_application
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _qt_application = QGuiApplication([])

    source_image = QImage(str(source)).convertToFormat(QImage.Format_RGB888)
    if source_image.isNull():
        raise RuntimeError(f"Không đọc được ảnh để render chuyển động: {source.name}.")

    frame_count = max(2, round(duration * _VIDEO_FPS))
    frame_end = max(1, frame_count - 1)
    base_scale = max(width / source_image.width(), height / source_image.height())
    pan_paths = (
        (0.30, 0.70, 0.50, 0.50),
        (0.70, 0.30, 0.50, 0.50),
        (0.50, 0.50, 0.30, 0.70),
        (0.50, 0.50, 0.70, 0.30),
    )
    start_x, end_x, start_y, end_y = pan_paths[direction % len(pan_paths)]
    command = [
        "ffmpeg", "-y", "-nostdin", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
        "-r", str(_VIDEO_FPS), "-i", "-", "-an", "-frames:v", str(frame_count),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12",
        "-pix_fmt", "yuv420p", str(output.name),
    ]
    process = _start(command, cwd=output.parent, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                     stderr=subprocess.PIPE)
    try:
        for frame_index in range(frame_count):
            progress = frame_index / frame_end
            eased = progress * progress * (3 - 2 * progress)
            zoom = 1.0 + 0.045 * eased
            scaled_width = source_image.width() * base_scale * zoom
            scaled_height = source_image.height() * base_scale * zoom
            available_x = max(0.0, scaled_width - width)
            available_y = max(0.0, scaled_height - height)
            pan_x = start_x + (end_x - start_x) * eased
            pan_y = start_y + (end_y - start_y) * eased
            left = available_x * pan_x
            top = available_y * pan_y
            canvas = QImage(width, height, QImage.Format_RGB888)
            canvas.fill(Qt.GlobalColor.black)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(QRectF(-left, -top, scaled_width, scaled_height), source_image)
            painter.end()
            raw = bytes(canvas.constBits())
            row_size = width * 3
            if canvas.bytesPerLine() != row_size:
                raw = b"".join(
                    raw[row * canvas.bytesPerLine():row * canvas.bytesPerLine() + row_size]
                    for row in range(height)
                )
            process.stdin.write(raw)
        process.stdin.close()
        error_output = process.stderr.read().decode("utf-8", errors="replace")
        process.stderr.close()
        return_code = process.wait(timeout=600)
    except Exception as error:
        process.kill()
        process.wait(timeout=30)
        check_cancelled()  # a cancel kills ffmpeg, which surfaces here as a broken pipe
        raise error
    finally:
        _release(process)
    check_cancelled()
    if return_code:
        raise RuntimeError(f"ffmpeg Ken Burns: {error_output[-1800:]}")


def _text_block_width(lines: list[str], font_path: Path, pixel_size: int) -> int:
    """Widest line in pixels, measured with Qt using the same font file drawtext uses."""
    from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QGuiApplication

    global _qt_application
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _qt_application = QGuiApplication([])
    families = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(font_path)))
    font = QFont(families[0] if families else "Arial")
    font.setPixelSize(pixel_size)
    metrics = QFontMetrics(font)
    return max(metrics.horizontalAdvance(line) for line in lines)


def run_media(arguments, directory, timeout=600):
    process = _start(arguments, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                     encoding="utf-8", errors="replace")
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    finally:
        _release(process)
    check_cancelled()
    if process.returncode:
        raise RuntimeError(f"{Path(arguments[0]).name}: {stderr[-1800:]}")
    return stdout


def probe(path):
    return json.loads(run_media(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                                  "-of", "json", str(path)], path.parent, 30))


def validate_runtime(storage: Path, directory: Path) -> None:
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            raise RuntimeError(f"Chưa cài {binary} hoặc chưa thêm vào PATH.")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe_path = directory / ".kv_write_test"
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink()
    except OSError as error:
        raise RuntimeError(f"Không ghi được thư mục render: {error}") from error
    minimum_mb = max(0, int(os.environ.get("KV_MIN_FREE_SPACE_MB", "100")))
    free_bytes = shutil.disk_usage(directory).free
    if free_bytes < minimum_mb * 1024 * 1024:
        raise RuntimeError(f"Không đủ dung lượng trống. Cần tối thiểu {minimum_mb} MB.")


def timestamp(seconds, separator=","):
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{milliseconds:03}"


def _speech_key(value: str) -> str:
    normalized = html.unescape(value or "").casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _find_body_start(cues, hook: str, body: str, duration: float) -> float:
    hook_key = _speech_key(hook)
    hook_words = hook_key.split()
    accumulated_words = []
    for index, (_start, end, content) in enumerate(cues):
        accumulated_words.extend(_speech_key(content).split())
        if hook_words and len(accumulated_words) >= len(hook_words):
            prefix = " ".join(accumulated_words[:len(hook_words)])
            if prefix == hook_key:
                boundary = cues[index + 1][0] if index + 1 < len(cues) else end
                return min(max(float(boundary), 1.0), max(1.0, duration - 0.1))

    body_key = _speech_key(body)
    anchor = body_key[:24]
    for start, _end, content in cues:
        cue_key = _speech_key(content)
        if anchor and anchor in cue_key and float(start) >= 1.0:
            return min(max(float(start), 1.0), max(1.0, duration - 0.1))
    total_chars = max(1, len(hook) + len(body))
    estimated = duration * len(hook) / total_chars
    return min(max(estimated, 3.0), max(3.0, duration - 0.2))


def _caption_chunks(content: str, max_chars: int = 56) -> list[str]:
    clean = " ".join((content or "").split())
    if not clean:
        return []
    chunks = textwrap.wrap(
        clean,
        width=max_chars,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if len(chunks) > 1 and len(chunks[-1]) < 18:
        words = " ".join(chunks[-2:]).split()
        midpoint = max(1, len(words) // 2)
        chunks[-2:] = [" ".join(words[:midpoint]), " ".join(words[midpoint:])]
    return chunks


def _asset_kind(path: Path, info: dict) -> str:
    suffix = path.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".webp"):
        return "image"
    return "video" if any(stream.get("codec_type") == "video" for stream in info.get("streams", [])) else "image"


# Edge TTS sometimes answers "no audio" for a minute or so; retries wait longer each time (None = give up).
_TTS_RETRY_PAUSES = (5, 15, 30, None)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+|\n+")
MIN_SCENE_SECONDS = 2.0


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip()]


def _word_key(value: str) -> str:
    return _speech_key(value).replace(" ", "")


def align_words(text: str, words: list[tuple[float, float, str]]) -> list[tuple[int, str, float, float]]:
    """Time every written token of `text` from Edge TTS word boundaries: (sentence index, token, start, end).

    Spoken words carry no punctuation and a number or abbreviation may be read as several words, so tokens are
    matched in order within a small window; tokens left unmatched take the gap between their neighbours.
    """
    tokens = [(index, token) for index, sentence in enumerate(_sentences(text)) for token in sentence.split()]
    keys = [_word_key(token) for _index, token in tokens]
    times: list = [None] * len(tokens)
    pointer, misses = 0, 0
    for start, end, word in words:
        key = _word_key(word)
        # After several unmatched words (text read differently than written) look further ahead to catch up.
        window = 6 if misses < 4 else 40
        for position in range(pointer, min(pointer + window, len(tokens))):
            if keys[position] and keys[position] == key:
                times[position] = (start, end)
                pointer, misses = position + 1, 0
                break
        else:
            misses += 1
    # Unmatched runs share the time between their matched neighbours evenly, so no token gets zero length.
    spoken_end = words[-1][1] if words else 0.0
    position = 0
    while position < len(times):
        if times[position] is not None:
            position += 1
            continue
        run_end = position
        while run_end < len(times) and times[run_end] is None:
            run_end += 1
        begin = times[position - 1][1] if position else 0.0
        finish = times[run_end][0] if run_end < len(times) else max(spoken_end, begin)
        step = max(0.0, finish - begin) / (run_end - position)
        for offset, index in enumerate(range(position, run_end)):
            times[index] = (begin + offset * step, begin + (offset + 1) * step)
        position = run_end
    return [(index, token, start, end) for (index, token), (start, end) in zip(tokens, times)]


def _sentence_cues(text: str, tokens) -> list[tuple[float, float, str]]:
    spans: dict[int, list[float]] = {}
    for index, _token, start, end in tokens:
        span = spans.setdefault(index, [start, end])
        span[0], span[1] = min(span[0], start), max(span[1], end)
    cues = [[spans[index][0], spans[index][1], sentence] for index, sentence in enumerate(_sentences(text))
            if index in spans]
    # Last resort: sentences squeezed onto one instant share the time up to the next distinct start by length.
    index = 0
    while index < len(cues):
        run_end = index + 1
        while run_end < len(cues) and cues[run_end][0] <= cues[index][0] + 0.05:
            run_end += 1
        finish = cues[run_end][0] if run_end < len(cues) else max(cue[1] for cue in cues[index:run_end])
        if run_end - index > 1 or finish - cues[index][0] < 0.05:
            finish = max(finish, cues[index][0] + 0.3 * (run_end - index))
            sizes = [max(1, len(cue[2])) for cue in cues[index:run_end]]
            moment = cues[index][0]
            for cue, size in zip(cues[index:run_end], sizes):
                share = (finish - cues[index][0]) * size / sum(sizes)
                cue[0], cue[1] = moment, moment + share
                moment += share
        index = run_end
    return [tuple(cue) for cue in cues]


def scene_starts(cues, scene_texts: list[str], duration: float, minimum: float = MIN_SCENE_SECONDS) -> list[float]:
    """Start of each scene at the moment its words begin to be spoken.

    Scene texts are consecutive slices of the narration, so each boundary's share of the scene characters is
    located on the sentence cues (spoken timeline) and snapped to a sentence start when close to one. Scenes are
    kept at least `minimum` seconds; when that cannot fit, scenes are spread evenly.
    """
    count = len(scene_texts)
    even = [index * duration / count for index in range(count)]
    if count < 2 or not cues or count * minimum > duration:
        return even
    scene_sizes = [max(1, len(_word_key(text))) for text in scene_texts]
    cue_sizes = [max(1, len(_word_key(content))) for _start, _end, content in cues]
    starts, before = [0.0], 0
    for index in range(1, count):
        before += scene_sizes[index - 1]
        position = before / sum(scene_sizes) * sum(cue_sizes)
        offset = 0
        moment = even[index]
        for cue_index, ((start, end, _content), size) in enumerate(zip(cues, cue_sizes)):
            if offset + size >= position:
                fraction = (position - offset) / size
                moment = start + fraction * (end - start)
                if fraction < 0.2:
                    moment = start
                elif fraction > 0.85 and cue_index + 1 < len(cues):
                    moment = cues[cue_index + 1][0]
                break
            offset += size
        starts.append(moment)
    for index in range(1, count):
        starts[index] = max(starts[index], starts[index - 1] + minimum)
    starts.append(duration)
    for index in range(count - 1, 0, -1):
        starts[index] = min(starts[index], starts[index + 1] - minimum)
    return starts[:count]


_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 384
PlayResY: 288
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,12,&H00FFFFFF,&H00FFFFFF,&H90000000,&H70000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
# Colour of the word being spoken (ASS colours are &HBBGGRR&): amber.
HIGHLIGHT_COLOUR = "&H00C8FF&"


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    return f"{centiseconds // 360000}:{centiseconds // 6000 % 60:02d}:{centiseconds // 100 % 60:02d}.{centiseconds % 100:02d}"


def highlight_subtitles(tokens, start_after: float, duration: float, max_chars: int = 56, line_chars: int = 32) -> str:
    """ASS subtitles showing a caption chunk with the word being spoken in HIGHLIGHT_COLOUR (TikTok style).

    Same play resolution and default header as the SRT path, so the shared force_style gives the same look.
    """
    chunks: list[list] = []
    for position, token in enumerate(tokens):
        # A short end of sentence ("Đằng.") stays with its chunk instead of flashing up alone.
        rest = len(" ".join(t[1] for t in tokens[position:] if t[0] == token[0]))
        same_sentence = chunks and chunks[-1][0][0] == token[0]
        if same_sentence and (len(" ".join(t[1] for t in chunks[-1] + [token])) <= max_chars or rest <= 12):
            chunks[-1].append(token)
        else:
            chunks.append([token])
    events = []
    for chunk_index, chunk in enumerate(chunks):
        words = [t[1].replace("{", "(").replace("}", ")").replace("\\", "/") for t in chunk]
        lines, current = [], []
        for position, word in enumerate(words):
            if current and len(" ".join(words[i] for i in current + [position])) > line_chars:
                lines.append(current)
                current = []
            current.append(position)
        lines.append(current)
        next_chunk_start = chunks[chunk_index + 1][0][2] if chunk_index + 1 < len(chunks) else duration
        for position, (_sentence, _token, start, end) in enumerate(chunk):
            finish = chunk[position + 1][2] if position + 1 < len(chunk) else end
            if position + 1 == len(chunk) and next_chunk_start - end < 1.0:
                finish = next_chunk_start  # keep the caption up through short pauses
            start, finish = max(start, start_after), min(finish, duration)
            if finish - start < 0.02:
                continue
            text = "\\N".join(" ".join(f"{{\\c{HIGHLIGHT_COLOUR}}}{words[i]}{{\\c}}" if i == position else words[i]
                                       for i in line) for line in lines)
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(finish)},Default,,0,0,0,,{text}")
    return _ASS_HEADER + "\n".join(events) + "\n"


def run_tts(coroutine, text: str):
    """Run a synthesize() call with a wait that grows with the narration.

    Edge TTS streams at about real-time speed or slower, so a fixed 180 s limit failed for 5-minute videos.
    """
    limit = 180 + 2 * len(text.split()) / WORDS_PER_SECOND
    try:
        return asyncio.run(asyncio.wait_for(coroutine, timeout=limit))
    except TimeoutError as error:
        raise RuntimeError(f"Edge TTS phản hồi quá chậm (quá {limit:.0f} giây). Kiểm tra mạng rồi thử lại.") from error


async def synthesize(text, voice, directory, rate="+0%", word_cues: list | None = None):
    """Speak `text` into voice.mp3 and return sentence cues (start, end, text).

    With `word_cues` (a list to fill), Edge TTS reports word boundaries instead; they are stored there and the
    sentence cues are rebuilt from them.
    """
    boundary = "WordBoundary" if word_cues is not None else "SentenceBoundary"
    for attempt, pause in enumerate(_TTS_RETRY_PAUSES):
        cues = []
        communicator = edge_tts.Communicate(text, voice, rate=rate, boundary=boundary)
        try:
            with (directory / "voice.mp3").open("wb") as audio:
                async for chunk in communicator.stream():
                    if chunk["type"] == "audio":
                        audio.write(chunk["data"])
                    elif chunk["type"] == boundary:
                        cues.append((chunk["offset"] / 10000000,
                                     (chunk["offset"] + chunk["duration"]) / 10000000,
                                     html.unescape(chunk["text"])))
        except NoAudioReceived as error:
            if pause is None:
                raise RuntimeError("Edge TTS tạm thời không trả giọng đọc (đã thử lại nhiều lần). "
                                   "Đợi một lát rồi thử lại.") from error
            logger.warning("tts_no_audio attempt=%d retry_in=%ss", attempt + 1, pause)
            await asyncio.sleep(pause)
            continue
        if not cues or not (directory / "voice.mp3").stat().st_size:
            raise RuntimeError("TTS không trả audio hoặc mốc phụ đề.")
        if word_cues is not None:
            word_cues[:] = cues
            return _sentence_cues(text, align_words(text, cues))
        return cues
    raise RuntimeError("TTS không trả audio sau khi thử lại.")


def render(snapshot, directory: Path, storage: Path, stage, tts=synthesize):
    directory.mkdir(parents=True, exist_ok=True)
    validate_runtime(storage, directory)
    stage("prepare_content", 5)
    script = snapshot["script"]
    hook = script["hook"].strip()
    body = script["body"].strip()
    narration = hook + "\n\n" + body
    (directory / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    stage("prepare_assets", 10)
    asset_entries = []
    asset_root = (storage / "assets").resolve()
    requested_assets = list(snapshot.get("asset_files") or [])
    if snapshot.get("asset_file") and snapshot["asset_file"] not in requested_assets:
        requested_assets.insert(0, snapshot["asset_file"])
    allowed_asset_suffixes = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".mkv", ".webm")
    for index, asset_name in enumerate(requested_assets):
        source = (asset_root / asset_name).resolve()
        if source.parent != asset_root or not source.is_file() or source.suffix.lower() not in allowed_asset_suffixes:
            raise RuntimeError("Asset local không tồn tại, không an toàn hoặc không đúng định dạng.")
        target = directory / f"article_asset_{index}{source.suffix.lower()}"
        shutil.copyfile(source, target)
        info = probe(target)
        if not any(stream.get("codec_type") == "video" for stream in info.get("streams", [])):
            raise RuntimeError("Asset không phải ảnh/video hợp lệ.")
        asset_entries.append((target, info, _asset_kind(target, info)))
    if not asset_entries:
        article_urls = list(snapshot.get("asset_urls") or [])
        if snapshot.get("asset_url") and snapshot["asset_url"] not in article_urls:
            article_urls.insert(0, snapshot["asset_url"])
        if snapshot.get("video_mode", "single_image") == "single_image":
            article_urls = article_urls[:1]
        for index, asset_url in enumerate(article_urls[:_MAX_ARTICLE_IMAGES]):
            try:
                suffix = Path(urlparse(asset_url).path).suffix.lower()
                if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
                    suffix = ".jpg"
                asset = directory / f"article_remote_asset_{index}{suffix}"
                asset.write_bytes(fetch_safe_bytes(asset_url, timeout=30, user_agent="KnowledgeVideo/0.1"))
                info = probe(asset)
                if not any(stream.get("codec_type") == "video" for stream in info.get("streams", [])):
                    continue
                asset_entries.append((asset, info, "image"))
            except Exception:
                continue
        if not asset_entries and snapshot.get("asset_url"):
            raise RuntimeError("Không tải được ảnh bài viết hoặc ảnh không đúng định dạng.")
    if asset_entries:
        (directory / "asset.json").write_text(
            json.dumps([info for _path, info, _kind in asset_entries], indent=2),
            encoding="utf-8",
        )
    music = snapshot.get("music_file")
    if music:
        music_root = (storage / "music").resolve()
        source = (music_root / music).resolve()
        if source.parent != music_root or not source.is_file() or source.suffix.lower() not in (".mp3", ".wav", ".m4a"):
            raise RuntimeError("Nhạc local không tồn tại hoặc không đúng định dạng MP3/WAV/M4A.")
        shutil.copyfile(source, directory / "music.audio")
    template_options = snapshot.get("template_options") or {}
    logo = None
    if template_options.get("logo_file"):
        asset_root = (storage / "assets").resolve()
        source = (asset_root / template_options["logo_file"]).resolve()
        if source.parent != asset_root or not source.is_file() or source.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise RuntimeError("Logo local không tồn tại hoặc không đúng định dạng PNG/JPG/JPEG/WEBP.")
        logo = directory / "logo_asset"
        shutil.copyfile(source, logo)
    stage("generate_tts", 20)
    subtitle_mode = snapshot.get("subtitle_style", "normal")
    if subtitle_mode not in ("normal", "highlight", "off"):
        raise RuntimeError("Kiểu phụ đề không hợp lệ.")
    words: list | None = [] if subtitle_mode == "highlight" else None
    for attempt in range(_TTS_ATTEMPTS):
        options = {"word_cues": words} if words is not None else {}
        cues = run_tts(tts(narration, snapshot["voice"], directory, snapshot.get("tts_rate", "+0%"), **options),
                       narration)
        duration = float(probe(directory / "voice.mp3")["format"]["duration"])
        # Edge TTS can drop the audio stream mid-way while still returning every sentence boundary.
        if duration >= cues[-1][0] + 0.5:
            break
        logger.warning("tts_audio_truncated attempt=%d audio=%.1fs last_cue_start=%.1fs", attempt + 1, duration, cues[-1][0])
    else:
        raise RuntimeError("Giọng đọc TTS bị cắt ngang giữa chừng sau nhiều lần thử. Kiểm tra mạng rồi render lại.")
    if not 0 < duration <= 1200:
        raise RuntimeError("Thời lượng audio phải trong khoảng 0–1200 giây.")
    banner_end = _find_body_start(cues, hook, body, duration)
    show_title_card = bool(template_options.get("show_title_card", True)) and snapshot.get("video_mode", "single_image") != "breaking_news"
    if not show_title_card:
        banner_end = 0.0
    stage("generate_subtitle", 40)
    sentence_cues = cues
    normalized_cues = []
    for index, (start, end, content) in enumerate(cues):
        end = min(end, cues[index + 1][0] if index + 1 < len(cues) else duration)
        parts = _caption_chunks(content)
        if not parts or end <= start:
            raise RuntimeError("Phụ đề rỗng hoặc mốc thời gian không hợp lệ.")
        span = (end - start) / len(parts)
        normalized_cues.extend((start + part_index * span, start + (part_index + 1) * span, part)
                               for part_index, part in enumerate(parts))
    cues = normalized_cues
    subtitle_cues = [
        (max(float(start), banner_end), float(end), content)
        for start, end, content in cues
        if float(end) > banner_end
    ]
    def subtitle_text(cue_list):
        srt, vtt = [], ["WEBVTT\n"]
        for index, (start, end, content) in enumerate(cue_list, 1):
            clean = " ".join(content.replace("{", "(").replace("}", ")").replace("<", "").replace(">", "").replace("\\", "/").split())
            start, end = max(0, start), min(duration, end)
            if end <= start:
                raise RuntimeError("Mốc thời gian phụ đề không hợp lệ.")
            wrapped = "\n".join(textwrap.wrap(
                clean,
                width=32,
                break_long_words=False,
                break_on_hyphens=False,
            ))
            srt.append(f"{index}\n{timestamp(start)} --> {timestamp(end)}\n{wrapped}\n")
            vtt.append(f"{timestamp(start, '.')} --> {timestamp(end, '.')}\n{wrapped}\n")
        return "\n".join(srt), "\n".join(vtt)

    full_srt, full_vtt = subtitle_text(cues)
    (directory / "subtitles.srt").write_text(full_srt, encoding="utf-8")
    (directory / "subtitles.vtt").write_text(full_vtt, encoding="utf-8")
    subtitle_file = ""
    for stale in ("body_subtitles.srt", "body_subtitles.ass"):
        (directory / stale).unlink(missing_ok=True)
    if subtitle_cues and subtitle_mode == "normal":
        body_srt, _body_vtt = subtitle_text(subtitle_cues)
        (directory / "body_subtitles.srt").write_text(body_srt, encoding="utf-8")
        subtitle_file = "body_subtitles.srt"
    elif subtitle_mode == "highlight":
        (directory / "body_subtitles.ass").write_text(
            highlight_subtitles(align_words(narration, words), banner_end, duration), encoding="utf-8")
        subtitle_file = "body_subtitles.ass"
    stage("build_timeline", 50)
    video_mode = snapshot.get("video_mode", "single_image")
    scene_count = max(1, len(asset_entries))
    scene_texts = snapshot.get("scene_texts") or []
    if snapshot.get("scene_timing") == "sentences" and len(scene_texts) == len(asset_entries) > 1:
        starts = scene_starts(sentence_cues, scene_texts, duration)
    else:
        starts = [index * duration / scene_count for index in range(scene_count)]
    lengths = [end - start for start, end in zip(starts, starts[1:] + [duration])]
    scenes = [
        {
            "index": index,
            "file": path.name,
            "kind": kind,
            "start": round(starts[index], 3),
            "end": round(starts[index] + lengths[index], 3),
        }
        for index, (path, _info, kind) in enumerate(asset_entries)
    ]
    (directory / "timeline.json").write_text(
        json.dumps({
            "duration": duration,
            "banner_end": banner_end,
            "video_mode": video_mode,
            "scenes": scenes,
            "cues": cues,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    title_lines = textwrap.wrap(" ".join(script["title"].split()), width=32) or [script["title"].strip()]
    # FFmpeg 8 drawtext draws any "\n" (and "\r") as a missing-glyph box, so each title line gets its own
    # single-line file and drawtext filter. Files are written with bare "\n" to avoid Windows "\r\n".
    for line_index, line in enumerate(title_lines):
        (directory / f"title_{line_index}.txt").write_text(line, encoding="utf-8", newline="\n")
    (directory / "title_dots.txt").write_text("●  ●  ●", encoding="utf-8", newline="\n")
    source_name = str(snapshot.get("source_name") or snapshot.get("source_id") or "Nguồn tổng hợp").strip()
    (directory / "source.txt").write_text(f"Nguồn: {source_name}", encoding="utf-8", newline="\n")
    stage("template_composition", 60)
    font = Path(os.environ.get("KV_VIDEO_FONT") or "C:/Windows/Fonts/arial.ttf")
    if template_options.get("font_file"):
        font_root = (storage / "assets").resolve()
        font = (font_root / template_options["font_file"]).resolve()
        if font.parent != font_root or not font.is_file() or font.suffix.lower() not in (".ttf", ".otf"):
            raise RuntimeError("Font local không tồn tại hoặc không đúng định dạng TTF/OTF.")
    if not font.is_file():
        raise RuntimeError("Thiếu font. Cấu hình KV_VIDEO_FONT trỏ tới font TTF hỗ trợ tiếng Việt.")
    shutil.copyfile(font, directory / "font.ttf")
    width, height = map(int, snapshot["resolution"].split("x"))
    template = snapshot.get("template", "news")
    video_mode = snapshot.get("video_mode", "single_image")
    if video_mode not in ("single_image", "news_report", "breaking_news"):
        raise RuntimeError("Chế độ video không hợp lệ.")
    show_source = bool(template_options.get("show_source", True))
    show_title_card = bool(template_options.get("show_title_card", True)) and video_mode != "breaking_news"
    if not show_title_card:
        banner_end = 0.0
    template_artwork = _rasterize_vector_template(template, width, directory)
    history_card = None
    if template in HISTORY_TEMPLATES:
        # Full-frame Qt card (title, badge, ornaments) replaces the drawtext title for history templates.
        history_card = render_title_card(template, script["title"], str(snapshot.get("title_badge") or ""),
                                         str(snapshot.get("title_label") or "Kiến thức lịch sử"),
                                         width, height, directory / "title_card.png")
        template_artwork = (history_card, height)
    grade = HISTORY_GRADES.get(template, "")
    background = "0x10213b" if template in ("news", "news-overview") else "0x181818"
    brand_color = template_options.get("brand_color", "#38bdf8")
    if not isinstance(brand_color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", brand_color):
        raise RuntimeError("Màu thương hiệu phải có dạng #RRGGBB.")
    title_position = template_options.get("title_position", "top")
    if title_position not in ("top", "center", "bottom"):
        raise RuntimeError("Vị trí tiêu đề không hợp lệ.")
    browser_card = show_title_card and not template_artwork and video_mode in ("single_image", "news_report")
    if history_card:
        artwork_path, artwork_height = template_artwork
        banner_y, banner_height = 0, height
        banner_fill, title_color, source_color = "", "white", "white"
        accent = brand_color
        title_size = 0
    elif browser_card:
        banner_y, banner_height = int(height * 0.56), int(height * 0.40)
        card_y, card_height = int(height * 0.59), int(height * 0.25)
        banner_fill, title_color, source_color = "0xF8D58A", "0x111827", "white"
        accent = brand_color
        title_size = max(40, min(60, width // 20))
    elif template_artwork:
        artwork_path, artwork_height = template_artwork
        banner_y, banner_height = max(int(height * 0.50), height - artwork_height - int(height * 0.06)), artwork_height
        banner_fill, title_color = "", "white"
        source_color = "#0b0d10" if template == "banner-yellow" else "white"
        accent = brand_color
        title_size = max(32, min(46, width // 23))
    elif template == "review":
        banner_y, banner_height = int(height * 0.47), int(height * 0.24)
        banner_fill, title_color, source_color = "0xFFFFFF@0.94", "0x111827", "0x334155"
        accent = brand_color
        title_size = max(34, width // 23)
    elif template == "minimal":
        banner_y, banner_height = int(height * 0.10), int(height * 0.19)
        banner_fill, title_color, source_color = "0x111827@0.88", "white", "0xCBD5E1"
        accent = brand_color
        title_size = max(34, width // 22)
    elif template == "news-overview":
        banner_y, banner_height = int(height * 0.10), int(height * 0.23)
        banner_fill, title_color, source_color = "0x062B50@0.94", "white", "0xDBEAFE"
        accent = brand_color
        title_size = max(34, width // 22)
    else:
        banner_y, banner_height = int(height * 0.08), int(height * 0.23)
        banner_fill, title_color, source_color = "0x0B1F3A@0.92", "white", "0xDBEAFE"
        accent = brand_color
        title_size = max(34, width // 22)
    banner_end_expr = f"{banner_end:.3f}"
    if history_card:
        source_y, title_y = 36, 0
    elif browser_card:
        source_y = 36
        title_y = card_y + int(card_height * 0.34)
        source_x = 36
    elif template_artwork:
        artwork_scale = width / 1200
        source_y = f"{banner_y + 153 * artwork_scale:.3f}-text_h/2"
        safe_top = banner_y + round(236 * artwork_scale)
        safe_bottom = banner_y + round(468 * artwork_scale)
        title_content_top = safe_top + round(18 * artwork_scale)
        title_content_bottom = safe_bottom + round(20 * artwork_scale) - round(18 * artwork_scale)
        centered_title_y = f"{(title_content_top + title_content_bottom) / 2:.3f}-text_h/2+{round(8 * artwork_scale)}"
        title_y = {
            "top": str(title_content_top),
            "center": centered_title_y,
            "bottom": f"{title_content_bottom}-text_h",
        }[title_position]
    else:
        source_y = banner_y + int(banner_height * 0.12)
        title_y = {
            "top": banner_y + int(banner_height * 0.30),
            "center": banner_y + int(banner_height * 0.42),
            "bottom": banner_y + int(banner_height * 0.54),
        }[title_position]
    source_x = "0.330*w-text_w/2" if template_artwork and not history_card else 36
    transitions = transition_names(template, snapshot.get("transition", "template"), max(0, len(asset_entries) - 1))
    overlap = transition_seconds(min(lengths), transitions)

    def scene_length(index: int) -> float:
        # Each scene but the last runs on through the transition into the next one.
        return lengths[index] + (overlap if index < len(asset_entries) - 1 else 0.0)

    render_entries = asset_entries
    if asset_entries:
        render_entries = []
        for index, (path, info, kind) in enumerate(asset_entries):
            if kind == "image":
                motion_path = directory / f"motion_scene_{index}.mp4"
                render_motion_scene(path, motion_path, width, height, scene_length(index), index)
                render_entries.append((motion_path, probe(motion_path), "video"))
            else:
                render_entries.append((path, info, kind))
    command = ["ffmpeg", "-y", "-nostdin", "-v", "error"]
    if render_entries:
        for path, _info, kind in render_entries:
            if kind == "image":
                command += ["-framerate", str(_VIDEO_FPS), "-loop", "1", "-i", path.name]
            else:
                command += ["-stream_loop", "-1", "-i", path.name]
        voice_index = len(render_entries)
    else:
        command += ["-f", "lavfi", "-i", f"color=c={background}:s={width}x{height}:r={_VIDEO_FPS}"]
        voice_index = 1
    command += ["-i", "voice.mp3"]
    scene_filters = []
    if render_entries:
        for index, (_path, _info, kind) in enumerate(render_entries):
            if kind == "image":
                progress = f"min(max(t/{lengths[index]:.6f},0),1)"
                eased_progress = f"({progress})*({progress})*(3-2*({progress}))"
                pan_paths = (
                    (f"0.28+0.44*{eased_progress}", "0.5"),
                    (f"0.72-0.44*{eased_progress}", "0.5"),
                    ("0.5", f"0.28+0.44*{eased_progress}"),
                    ("0.5", f"0.72-0.44*{eased_progress}"),
                )
                pan_x, pan_y = pan_paths[index % len(pan_paths)]
                zoom = f"(1+0.055*{eased_progress})"
                visual_filter = (
                    f"fps={_VIDEO_FPS},scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},"
                    f"scale=w='ceil(iw*{zoom}/2)*2':h='ceil(ih*{zoom}/2)*2':"
                    f"eval=frame:flags=bicubic,"
                    f"crop=w={width}:h={height}:x='(iw-ow)*({pan_x})':y='(ih-oh)*({pan_y})',"
                    "eq=brightness=-0.08:saturation=0.95,"
                    f"{grade}"
                )
            else:
                visual_filter = scene_look(width, height, grade)
            label = f"scene{index}"
            scene_filters.append(
                f"[{index}:v]{visual_filter}setsar=1,trim=duration={scene_length(index):.3f},"
                f"setpts=PTS-STARTPTS,format=yuv420p,settb=AVTB[{label}]"
            )
        scene_filters.extend(join_scenes(len(render_entries), starts, transitions, overlap))
        # The clone pad only covers rounding in the per-scene trims.
        scene_filters.append(
            f"[joined]tpad=stop_mode=clone:stop_duration=1,"
            f"trim=duration={duration:.3f},setpts=PTS-STARTPTS[vsource]"
        )
    else:
        scene_filters.append("[0:v]null[vsource]")
    next_input_index = voice_index + 1
    template_index = None
    if template_artwork:
        template_index = next_input_index
        command += ["-loop", "1", "-i", str(artwork_path)]
        next_input_index += 1
    music_index = None
    if music:
        music_index = next_input_index
        command += ["-stream_loop", "-1", "-i", "music.audio"]
        next_input_index += 1
    logo_index = None
    if logo:
        logo_index = next_input_index
        command += ["-loop", "1", "-i", "logo_asset"]
    if template_artwork:
        scene_filters.extend([
            f"[{template_index}:v]format=rgba[template]",
            f"[vsource][template]overlay=x=0:y={banner_y}:eof_action=repeat:enable='lt(t,{banner_end_expr})'[vbanner]",
        ])
        composition_label = "[vbanner]"
    elif browser_card:
        card_x = int(width * 0.08)
        card_width = int(width * 0.84)
        video_filter = (
            f"[vsource]drawbox=x=0:y={banner_y}:w=iw:h={height - banner_y}:color={banner_fill}:t=fill:enable='lt(t,{banner_end_expr})',"
            f"drawbox=x={card_x}:y={card_y}:w={card_width}:h={card_height}:color=0xFFFCF3@0.98:t=fill:enable='lt(t,{banner_end_expr})',"
            f"drawtext=fontfile=font.ttf:textfile=title_dots.txt:expansion=none:fontcolor=0xF59E0B:fontsize={max(24, width // 36)}:x={card_x + card_width - int(width * 0.18)}:y={card_y + 26}:enable='lt(t,{banner_end_expr})',"
        )
        composition_label = ""
    else:
        video_filter = (
            "[vsource]"
            f"drawbox=x=0:y={banner_y}:w=iw:h={banner_height}:color={banner_fill}:t=fill:enable='lt(t,{banner_end_expr})',"
            f"drawbox=x=0:y={banner_y}:w=iw:h={banner_height}*0.025:color=0x{accent[1:]}:t=fill:enable='lt(t,{banner_end_expr})',"
        )
        composition_label = ""
    subtitle_font_size = max(9, min(12, width // 100))
    subtitle_margin = max(42, height // 40)
    subtitle_style = (
        f"FontName=Arial,FontSize={subtitle_font_size},"
        "PrimaryColour=&H00FFFFFF,BorderStyle=1,"
        "BackColour=&H70000000,Outline=2,OutlineColour=&H90000000,Shadow=0,"
        f"Alignment=2,MarginL={max(60, width // 14)},"
        f"MarginR={max(60, width // 14)},MarginV={subtitle_margin},WrapStyle=2"
    )
    subtitle_filter = (
        f"subtitles={subtitle_file}:original_size={width}x{height}:force_style='{subtitle_style}'"
        if subtitle_file else "null"
    )
    source_overlay = ""
    if show_source:
        source_overlay = (
            f"drawtext=fontfile=font.ttf:textfile=source.txt:expansion=none:fontcolor={source_color}:"
            f"fontsize={max(22, width // 42)}:x={source_x}:y={source_y}:borderw=2:bordercolor=0x000000@0.55,"
        )
    title_overlay = ""
    if show_title_card and not history_card:
        line_height = round(title_size * 1.17) + (-8 if template_artwork else 2)
        block_height = line_height * len(title_lines)
        if template_artwork:
            # Former multi-line block positions, recomputed from the block height instead of drawtext's text_h.
            block_top = {
                "top": title_content_top,
                "center": (title_content_top + title_content_bottom) / 2 - block_height / 2 + round(8 * artwork_scale),
                "bottom": title_content_bottom - block_height,
            }[title_position]
            line_x = "(w-text_w)/2"
        else:
            block_top = float(title_y)
            # Left-aligned lines inside a horizontally centred block, as text_align=left used to do.
            line_x = f"(w-{_text_block_width(title_lines, directory / 'font.ttf', title_size)})/2"
        for line_index in range(len(title_lines)):
            title_overlay += (
                f"drawtext=fontfile=font.ttf:textfile=title_{line_index}.txt:expansion=none:fontcolor={title_color}:"
                f"fontsize={title_size}:x={line_x}:y={block_top + line_index * line_height:.1f}:"
                f"borderw={'0' if template_artwork else '2'}:bordercolor=0x000000@0.55:"
                f"shadowx=1:shadowy=1:shadowcolor={'0x700000@0.55' if template_artwork else '0x000000@0.55'}:"
                f"enable='lt(t,{banner_end_expr})',"
            )
    text_filter = source_overlay + title_overlay + subtitle_filter
    if browser_card or not template_artwork:
        video_filter += text_filter
        scene_filters.append(video_filter + "[vtext]")
    else:
        scene_filters.append(
            composition_label + source_overlay + title_overlay
            + f"{subtitle_filter}[vtext]"
        )
    filter_complex = []
    if logo:
        filter_complex.extend(scene_filters)
        filter_complex.append(
            f"[{logo_index}:v]format=rgba,scale=iw*0.18:-1[logo];"
            "[vtext][logo]overlay=x=W-w-24:y=24[vout]"
        )
    else:
        filter_complex.extend(scene_filters)
        filter_complex.append("[vtext]null[vout]")
    if music:
        filter_complex.append(
            f"[{voice_index}:a]asplit=2[voice][side];[{music_index}:a]volume={snapshot['music_volume']/100}[music];"
            "[music][side]sidechaincompress=threshold=0.025:ratio=8[duck];"
            "[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[audio]"
        )
    else:
        filter_complex.append(f"[{voice_index}:a]anull[audio]")
    command += ["-filter_complex", ";".join(filter_complex), "-map", "[vout]", "-map", "[audio]",
                "-t", str(duration), "-c:v", "libx264", "-preset",
                os.environ.get("KV_FFMPEG_PRESET", "fast"),
                "-crf", os.environ.get("KV_VIDEO_CRF", "20"), "-threads", "2",
                "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-b:a", "128k", "-movflags", "+faststart", "render.mp4"]
    stage("ffmpeg_render", 70)
    run_media(command, directory)
    stage("validate", 95)
    info = probe(directory / "render.mp4")
    videos = [stream for stream in info["streams"] if stream["codec_type"] == "video"]
    audios = [stream for stream in info["streams"] if stream["codec_type"] == "audio"]
    if not videos or not audios or videos[0]["width"] != width or videos[0]["height"] != height:
        raise RuntimeError("Video thiếu stream hoặc sai độ phân giải.")
    if abs(float(info["format"]["duration"]) - duration) > 1:
        raise RuntimeError("Thời lượng video không khớp audio.")
    run_media(["ffmpeg", "-v", "error", "-i", "render.mp4", "-f", "null", "-"], directory)
    (directory / "validation.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    (directory / "render.mp4").replace(directory / "final.mp4")
