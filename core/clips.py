"""Video clips as scene footage for the "Tạo video clip" flow.

One source video per run: found by keyword among Creative Commons YouTube videos, or pasted by the user. It is
downloaded once at 360p to split into shots and look at them; only the shots picked for the scenes are fetched in
high quality at render time, cut to 9:16, with channel logos kept out of the frame or blurred.
"""
import base64
import json
import logging
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

import yt_dlp

from core.ai import BaseAIProvider
from core.config import output_directory
from core.network_security import fetch_safe_bytes
from core.video_pipeline import RenderCancelled, check_cancelled, probe, run_media

logger = logging.getLogger("kv.clips")

# YouTube search filter "Creative Commons" (sp=EgIwAQ==): only videos whose owner allows reuse with credit.
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
# Titles that say the video is animated, AI-made or a slide deck (checked before spending time on a video).
_UNREAL_WORDS = ("hoạt hình", "animation", "animated", "cartoon", "3d", "sora", "veo", "midjourney", "notebooklm",
                 "slide", " ai ", "a.i.", "(ai)", "#ai")
KIND_LABELS = {
    "live_footage": "Quay thật",
    "archival_footage": "Tư liệu cũ",
    "animation_3d": "Hoạt hình / 3D",
    "illustration": "Tranh vẽ (slideshow)",
    "slides": "Slide / chữ",
    "talking_head": "Người dẫn nói",
}
CONTENT_FILTERS = {
    "real": ("Chỉ tư liệu thật", {"live_footage", "archival_footage"}),
    "any": ("Cho phép hoạt hình", {"live_footage", "archival_footage", "animation_3d"}),
}
MIN_SHOT_SECONDS = 1.5
MAX_SHOT_SECONDS = 8.0
MAX_SHOTS = 60
MAX_SOURCE_SECONDS = 3 * 3600
# A short shot is slowed down at most this much to fill its scene; beyond that the render loops it.
MAX_SLOWDOWN = 1.6


class ClipError(Exception):
    pass


class _QuietLogger:
    """yt-dlp prints to the console by default; route its messages to the app log instead."""

    def debug(self, message):
        pass

    def info(self, message):
        pass

    def warning(self, message):
        logger.info("yt_dlp_warning %s", message[:300])

    def error(self, message):
        logger.warning("yt_dlp_error %s", message[:300])


def _deno_path() -> str | None:
    """Deno lets yt-dlp solve YouTube's JavaScript challenges; without it some links are refused now and then.
    A winget install only reaches PATH in new terminals, so its usual location is checked too."""
    found = shutil.which("deno")
    if found:
        return found
    for candidate in (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "deno.exe",
                      Path.home() / ".deno" / "bin" / "deno.exe"):
        if candidate.is_file():
            return str(candidate)
    return None


def _real_ffmpeg_dir() -> str | None:
    """Folder of the real ffmpeg when "ffmpeg" on PATH is a Chocolatey shim.

    Section downloads through the shim failed now and then ("ffmpeg exited with code 3436169992", 1 in 5 tries),
    the real binary did not (5 of 5).
    """
    found = shutil.which("ffmpeg") or ""
    if "chocolatey" not in found.lower():
        return None
    lib = Path(found).resolve().parents[1] / "lib"
    real = next(iter(sorted(lib.glob("ffmpeg*/tools/**/bin/ffmpeg.exe"))), None)
    return str(real.parent) if real else None


_YDL_BASE = {"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 30, "logger": _QuietLogger()}
if _deno_path():
    _YDL_BASE["js_runtimes"] = {"deno": {"path": _deno_path()}}
if _real_ffmpeg_dir():
    _YDL_BASE["ffmpeg_location"] = _real_ffmpeg_dir()
# Downloads that fail are tried again with fresh links (YouTube sometimes refuses a link for a moment).
_DOWNLOAD_PAUSES = (3, 8, None)


def cache_directory() -> Path:
    directory = output_directory() / "_clip_cache"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def cache_limit_mb() -> int:
    try:
        return max(200, int(os.environ.get("KV_CLIP_CACHE_MB") or 2048))
    except ValueError:
        return 2048


def cache_size() -> int:
    return sum(path.stat().st_size for path in cache_directory().rglob("*") if path.is_file())


def trim_cache(keep: set[Path] = frozenset()) -> None:
    """Delete the oldest cached files until the cache fits its size limit (Settings)."""
    files = sorted((path for path in cache_directory().rglob("*") if path.is_file()), key=lambda path: path.stat().st_mtime)
    total, limit = sum(path.stat().st_size for path in files), cache_limit_mb() * 1024 * 1024
    for path in files:
        if total <= limit:
            break
        if path in keep:
            continue
        total -= path.stat().st_size
        path.unlink(missing_ok=True)


def clear_cache() -> None:
    for path in cache_directory().rglob("*"):
        if path.is_file():
            path.unlink(missing_ok=True)


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def youtube_id(link: str) -> str:
    """Video id of a pasted YouTube link (watch, youtu.be, shorts, embed) or a bare 11-character id."""
    text = (link or "").strip()
    if _YOUTUBE_ID.match(text):
        return text
    parsed = urlparse(text if "://" in text else "https://" + text)
    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        raise ClipError("Chỉ hỗ trợ link YouTube (youtube.com/watch?v=..., youtu.be/..., youtube.com/shorts/...).")
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
        candidate = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
    else:
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    if not _YOUTUBE_ID.match(candidate):
        raise ClipError("Không đọc được mã video trong link YouTube này.")
    return candidate


def _is_unreal_title(title: str) -> bool:
    text = f" {title.casefold()} "
    return any(word in text for word in _UNREAL_WORDS)


def search(query: str, limit: int = 20) -> list[dict]:
    """YouTube videos for `query`..."""
    url = f"https://www.youtube.com/results?search_query={quote(query)}"
    try:
        with yt_dlp.YoutubeDL({**_YDL_BASE, "extract_flat": True, "playlistend": limit}) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as error:
        raise ClipError("Không tìm được trên YouTube. Kiểm tra mạng rồi thử lại.") from error
    results = []
    for entry in info.get("entries") or []:
        video_id = entry.get("id") or ""
        if _YOUTUBE_ID.match(video_id):
            results.append({"id": video_id, "title": entry.get("title") or "",
                            "channel": entry.get("channel") or entry.get("uploader") or "",
                            "duration": float(entry.get("duration") or 0)})
    return results


def video_info(video_id: str) -> dict:
    try:
        with yt_dlp.YoutubeDL(_YDL_BASE) as ydl:
            info = ydl.extract_info(watch_url(video_id), download=False)
    except yt_dlp.utils.DownloadError as error:
        raise ClipError(f"Không đọc được video {video_id} (video riêng tư, bị chặn hoặc đã xóa).") from error
    return info


def _source_fields(info: dict) -> dict:
    return {"id": info["id"], "url": watch_url(info["id"]), "title": info.get("title") or "",
            "channel": info.get("channel") or info.get("uploader") or "",
            "license": info.get("license") or "", "duration": float(info.get("duration") or 0)}


def is_creative_commons(license_text: str) -> bool:
    return "creative commons" in (license_text or "").casefold()


def credit_line(source: dict) -> str:
    license_text = "CC BY" if is_creative_commons(source.get("license", "")) else ""
    parts = [f"\"{source.get('title', '')}\" - {source.get('channel', '')}".strip(" -"), source.get("url", "")]
    return "\n".join(part for part in parts if part) + (f" ({license_text})" if license_text else "")


# ---------- looking at a video: storyboard sheets and the local vision model ----------

def _vision_model() -> str:
    return os.environ.get("KV_VISION_MODEL") or "gemma3"


def _ollama_url() -> str:
    return (os.environ.get("KV_OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/").removesuffix("/api/chat")


def gemini_vision(provider):
    """Vision function backed by a Gemini provider (Google or a gateway) instead of the local Ollama model."""
    def look(prompt: str, image_paths: list[Path], schema: dict) -> dict:
        return provider.generate_json_images(prompt, image_paths, schema)

    return look


def ollama_vision(prompt: str, image_paths: list[Path], schema: dict) -> dict:
    """Ask the local Ollama vision model about images; the answer is shaped by `schema`.

    Every vision step takes a function with this signature (`vision`), so Gemini can look instead
    (gemini_vision).
    """
    payload = {
        "model": _vision_model(),
        "messages": [{"role": "user", "content": prompt,
                      "images": [base64.b64encode(path.read_bytes()).decode("ascii") for path in image_paths]}],
        "format": schema, "stream": False, "options": {"temperature": 0},
    }
    request = Request(f"{_ollama_url()}/api/chat", data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json", "User-Agent": "KnowledgeVideo/0.1"}, method="POST")
    try:
        timeout = float(os.environ.get("KV_OLLAMA_TIMEOUT_SECONDS") or 240)
    except ValueError:
        timeout = 240.0
    try:
        with urlopen(request, timeout=timeout) as response:
            content = (json.loads(response.read().decode("utf-8")).get("message") or {}).get("content") or ""
    except HTTPError as error:
        if error.code == 404:
            raise ClipError(f"Ollama chưa có model xem ảnh '{_vision_model()}'. Chạy: ollama pull {_vision_model()}") from error
        raise ClipError(f"Ollama trả lỗi HTTP {error.code} khi xem khung hình.") from error
    except (TimeoutError, URLError, OSError) as error:
        raise ClipError("Không kết nối được Ollama để xem khung hình video. Hãy mở Ollama.") from error
    try:
        data = json.loads(content)
    except ValueError as error:
        raise ClipError("Model xem ảnh trả về không đúng định dạng.") from error
    if not isinstance(data, dict):
        raise ClipError("Model xem ảnh trả về không đúng định dạng.")
    return data


_CLASSIFY_PROMPT = (
    "This image is a grid of thumbnails sampled from one YouTube video. Classify the video.\n"
    "kind: one of live_footage (real camera footage, modern), archival_footage (old real film), "
    "slides (presentation slides or text screens), illustration (drawn or painted images, slideshow), "
    "animation_3d (3D or cartoon animation), talking_head (a presenter talking to camera).\n"
    "watermark: true if a channel logo or station name is burned into the corner of the frames.\n"
    "Answer JSON only."
)
_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": list(KIND_LABELS)}, "watermark": {"type": "boolean"}},
    "required": ["kind", "watermark"],
}


def storyboard_sheet(info: dict, directory: Path) -> Path | None:
    """Two storyboard sheets from the middle of the video, stacked into one image (tiny, no video download)."""
    boards = [item for item in info.get("formats") or [] if str(item.get("format_id", "")).startswith("sb")]
    if not boards:
        return None
    fragments = max(boards, key=lambda item: item.get("width") or 0).get("fragments") or []
    if not fragments:
        return None
    picks = sorted({len(fragments) // 3, (2 * len(fragments)) // 3} if len(fragments) > 2 else {0})
    directory.mkdir(parents=True, exist_ok=True)
    parts = []
    for number, index in enumerate(picks):
        path = directory / f"{info['id']}_sb{number}.jpg"
        path.write_bytes(fetch_safe_bytes(fragments[index]["url"], timeout=30))
        parts.append(path)
    sheet = directory / f"{info['id']}_board.jpg"
    if len(parts) == 1:
        parts[0].replace(sheet)
        return sheet
    run_media(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", parts[0].name, "-i", parts[1].name, "-filter_complex",
               "[0:v]scale=960:-2[a];[1:v]scale=960:-2[b];[a][b]vstack", sheet.name], directory, 60)
    for path in parts:
        path.unlink(missing_ok=True)
    return sheet


def classify(sheet: Path, vision=ollama_vision) -> tuple[str, bool]:
    data = vision(_CLASSIFY_PROMPT, [sheet], _CLASSIFY_SCHEMA)
    kind = data.get("kind") if data.get("kind") in KIND_LABELS else "slides"
    return kind, bool(data.get("watermark"))


def find_candidates(query: str, content_filter: str, progress=None, limit: int = 8, vision=ollama_vision) -> list[dict]:
    """Creative Commons videos for the topic, each looked at through its storyboard and classified.

    Videos whose kind is allowed by `content_filter` come first. Logos do not exclude a video: they are cropped
    out or blurred when the scenes are cut.
    """
    allowed = CONTENT_FILTERS[content_filter][1]
    found = search(query)
    if content_filter == "real":
        found = [item for item in found if not _is_unreal_title(item["title"])]
    found = [item for item in found if 45 <= item["duration"] <= MAX_SOURCE_SECONDS][:limit]
    boards = cache_directory() / "boards"
    candidates = []
    for number, item in enumerate(found, 1):
        check_cancelled()
        if progress:
            progress(f"Xem thử video {number}/{len(found)}: {item['title'][:50]}", round(100 * (number - 1) / max(1, len(found))))
        try:
            info = video_info(item["id"])
            sheet = storyboard_sheet(info, boards)
            kind, watermark = classify(sheet, vision) if sheet else ("slides", False)
        except ClipError as error:
            logger.info("clip_candidate_skipped id=%s reason=%s", item["id"], error)
            continue
        except RenderCancelled:
            raise
        except (OSError, ValueError, RuntimeError) as error:
            logger.info("clip_candidate_skipped id=%s reason=%s", item["id"], type(error).__name__)
            continue
        candidates.append({**_source_fields(info), "kind": kind, "watermark": watermark,
                           "allowed": kind in allowed, "board": str(sheet) if sheet else ""})
    candidates.sort(key=lambda item: not item["allowed"])
    return candidates


# ---------- preparing the chosen source: 360p copy, shots, logos ----------

def _download(video_id: str, options: dict) -> None:
    for attempt, pause in enumerate(_DOWNLOAD_PAUSES, 1):
        check_cancelled()
        try:
            # A new YoutubeDL per attempt fetches fresh stream links.
            with yt_dlp.YoutubeDL({**_YDL_BASE, **options}) as ydl:
                ydl.download([watch_url(video_id)])
            return
        except yt_dlp.utils.DownloadError as error:
            logger.warning("youtube_download_failed id=%s attempt=%d reason=%s", video_id, attempt,
                           re.sub(r"\x1b\[[0-9;]*m", "", str(error))[:300])
            if pause is None:
                raise ClipError(f"Không tải được video {video_id} từ YouTube (đã thử {attempt} lần).") from error
            time.sleep(pause)


def analysis_copy(video_id: str) -> Path:
    """360p video-only copy in the cache, downloaded once."""
    cache = cache_directory()
    existing = [path for path in cache.glob(f"{video_id}_360.*") if not path.name.endswith(".part")]
    if not existing:
        _download(video_id, {"format": "bv*[height<=360][ext=mp4]/bv*[height<=360]/wv*",
                             "outtmpl": str(cache / f"{video_id}_360.%(ext)s")})
        existing = [path for path in cache.glob(f"{video_id}_360.*") if not path.name.endswith(".part")]
    if not existing:
        raise ClipError("Tải video xong nhưng không thấy file.")
    path = existing[0]
    os.utime(path)  # most recently used, so trimming the cache removes other videos first
    trim_cache({path})
    return path


def _stderr(arguments: list[str], directory: Path, timeout: int = 600) -> str:
    result = subprocess.run(arguments, cwd=directory, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return result.stderr


def detect_shots(path: Path, duration: float, threshold: float = 0.3) -> list[dict]:
    """Continuous shots between scene cuts; long takes are split so one take can serve several scenes."""
    output = _stderr(["ffmpeg", "-hide_banner", "-nostdin", "-i", path.name, "-vf",
                      f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"], path.parent)
    cuts = sorted(float(value) for value in re.findall(r"pts_time:([\d.]+)", output))
    bounds = [0.0] + [cut for cut in cuts if 0 < cut < duration] + [duration]
    shots = []
    for start, end in zip(bounds, bounds[1:]):
        # A little margin keeps the cut frame and fades at the shot edges out of the clip.
        start, end = start + 0.15, end - 0.15
        length = end - start
        if length < MIN_SHOT_SECONDS:
            continue
        pieces = math.ceil(length / MAX_SHOT_SECONDS)
        for piece in range(pieces):
            shots.append({"start": round(start + piece * length / pieces, 3),
                          "end": round(start + (piece + 1) * length / pieces, 3)})
    if len(shots) > MAX_SHOTS:
        step = len(shots) / MAX_SHOTS
        shots = [shots[int(index * step)] for index in range(MAX_SHOTS)]
    return shots


def shot_thumbnails(path: Path, shots: list[dict], directory: Path, prefix: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, shot in enumerate(shots):
        name = f"{prefix}_{index:03d}.jpg"
        middle = (shot["start"] + shot["end"]) / 2
        run_media(["ffmpeg", "-y", "-nostdin", "-v", "error", "-ss", f"{middle:.3f}", "-i", str(path),
                   "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "4", name], directory, 60)
        shot["thumb"] = name


_LOGO_W, _LOGO_H = 192, 108


def detect_logos(path: Path, duration: float, samples: int = 30) -> list[list[float]]:
    """Regions that stay the same across the whole video (channel logos, station names), as [x, y, w, h] fractions.

    Frames are sampled over the whole video, i.e. across many different shots; natural edges move from frame
    to frame while a burned-in logo keeps its edges in the same pixels.
    """
    start, span = duration * 0.05, duration * 0.9
    process = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{span:.2f}", "-i", str(path), "-vf",
         f"fps={samples}/{span:.3f},scale={_LOGO_W}:{_LOGO_H},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, timeout=300, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    size = _LOGO_W * _LOGO_H
    frames = [process.stdout[offset:offset + size] for offset in range(0, len(process.stdout) - size + 1, size)]
    if len(frames) < 8:
        return []
    # Tuned on 3 videos (2 with station logos, 1 without): film grain gives every pixel edges now and then, so a
    # low edge threshold with a high share of frames separates logos from grain.
    counts = [0] * size
    for frame in frames:
        for y in range(_LOGO_H - 1):
            row = y * _LOGO_W
            for x in range(_LOGO_W - 1):
                pixel = frame[row + x]
                if abs(pixel - frame[row + x + 1]) + abs(pixel - frame[row + _LOGO_W + x]) > 20:
                    counts[row + x] += 1
    persistent = {index for index, count in enumerate(counts) if count >= 0.75 * len(frames)}
    boxes: list[list[int]] = []
    while persistent:
        seed = persistent.pop()
        stack, members = [seed], [seed]
        while stack:
            index = stack.pop()
            x, y = index % _LOGO_W, index // _LOGO_W
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    neighbour = (y + dy) * _LOGO_W + (x + dx)
                    if neighbour in persistent and 0 <= x + dx < _LOGO_W:
                        persistent.discard(neighbour)
                        stack.append(neighbour)
                        members.append(neighbour)
        xs, ys = [index % _LOGO_W for index in members], [index // _LOGO_W for index in members]
        left, top, right, bottom = min(xs), min(ys), max(xs) + 1, max(ys) + 1
        # Letterbox bars and frame borders make long straight lines; logos are small blocks.
        if len(members) < 20 or right - left > 0.45 * _LOGO_W or bottom - top > 0.35 * _LOGO_H:
            continue
        pad = 4
        boxes.append([max(0, left - pad), max(0, top - pad), min(_LOGO_W, right + pad), min(_LOGO_H, bottom + pad)])
    # Parts of one logo (an emblem and its text) come out as separate blocks whose padded boxes touch.
    merged = True
    while merged:
        merged = False
        for first in range(len(boxes)):
            for second in range(first + 1, len(boxes)):
                a, b = boxes[first], boxes[second]
                if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                    boxes[first] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del boxes[second]
                    merged = True
                    break
            if merged:
                break
    return sorted([round(left / _LOGO_W, 4), round(top / _LOGO_H, 4), round((right - left) / _LOGO_W, 4),
                   round((bottom - top) / _LOGO_H, 4)] for left, top, right, bottom in boxes)


def prepare_source(video_id: str, thumbs_directory: Path, progress=None) -> dict:
    """Everything the scene step needs about the source video: metadata, shots with thumbnails, logo regions."""
    def report(text: str, percent: int) -> None:
        if progress:
            progress(text, percent)

    report("Đọc thông tin video", 2)
    info = video_info(video_id)
    source = _source_fields(info)
    if not 10 <= source["duration"] <= MAX_SOURCE_SECONDS:
        raise ClipError("Video nguồn phải dài từ 10 giây đến 3 giờ.")
    logger.info("clip_source id=%s duration=%.0fs channel=%s", video_id, source["duration"], source["channel"])
    check_cancelled()
    report("Tải bản 360p để phân tích", 10)
    started = time.monotonic()
    path = analysis_copy(video_id)
    logger.info("clip_analysis_copy size=%.1fMB took=%.1fs", path.stat().st_size / 1e6, time.monotonic() - started)
    check_cancelled()
    report("Tách shot", 45)
    shots = detect_shots(path, source["duration"])
    if not shots:
        raise ClipError("Không tách được shot nào đủ dài từ video này.")
    logger.info("clip_shots count=%d (max %d)", len(shots), MAX_SHOTS)
    report(f"Tạo ảnh cho {len(shots)} shot", 60)
    shot_thumbnails(path, shots, thumbs_directory, video_id)
    report("Dò logo/watermark", 85)
    logos = detect_logos(path, source["duration"])
    logger.info("clip_logos count=%d boxes=%s", len(logos), logos)
    report(f"Xong: {len(shots)} shot, {len(logos)} vùng logo", 100)
    return {**source, "shots": shots, "logos": logos, "logos_from": "auto"}


# ---------- matching shots to scenes ----------

_DESCRIBE_SCHEMA = {
    "type": "object",
    "properties": {"frames": {"type": "array", "items": {
        "type": "object", "properties": {"n": {"type": "integer"}, "desc": {"type": "string"}},
        "required": ["n", "desc"]}}},
    "required": ["frames"],
}


def _contact_sheet(paths: list[Path], output: Path) -> None:
    """3x3 grid of shot frames, each numbered 1-9 in its corner, so the model can refer to them."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    tile_w, tile_h = 320, 180
    sheet = QImage(tile_w * 3, tile_h * 3, QImage.Format_RGB32)
    sheet.fill(QColor("#000000"))
    painter = QPainter(sheet)
    painter.setFont(QFont("Arial", 22, QFont.Bold))
    for number, path in enumerate(paths):
        x, y = (number % 3) * tile_w, (number // 3) * tile_h
        image = QImage(str(path))
        if not image.isNull():
            painter.drawImage(QRect(x, y, tile_w, tile_h), image)
        painter.fillRect(x, y, 40, 36, QColor("#ffd400"))
        painter.setPen(QColor("#000000"))
        painter.drawText(QRect(x, y, 40, 36), Qt.AlignCenter, str(number + 1))
    painter.end()
    if not sheet.save(str(output), "JPG", 85):
        raise ClipError("Không tạo được ảnh ghép khung hình.")


def describe_shots(source: dict, thumbs_directory: Path, progress=None, vision=ollama_vision) -> None:
    """Short English description of each shot (fills shot["desc"]), nine shots per vision call."""
    shots = source["shots"]
    groups = [list(range(start, min(start + 9, len(shots)))) for start in range(0, len(shots), 9)]
    for number, group in enumerate(groups, 1):
        check_cancelled()
        if progress:
            progress(f"AI xem shot {group[0] + 1}-{group[-1] + 1}/{len(shots)}", round(100 * (number - 1) / len(groups)))
        sheet = thumbs_directory / f"_grid_{number}.jpg"
        _contact_sheet([thumbs_directory / shots[index]["thumb"] for index in group], sheet)
        prompt = (f"This image is a 3x3 grid of {len(group)} numbered video frames (yellow numbers 1-{len(group)}, "
                  "left to right, top to bottom). For each numbered frame write a short English description "
                  "(max 12 words) of what is visible: people, objects, place, action. Mention on-screen text "
                  "or title cards if any. Answer JSON only.")
        try:
            data = vision(prompt, [sheet], _DESCRIBE_SCHEMA)
        finally:
            sheet.unlink(missing_ok=True)
        for item in data.get("frames") or []:
            if isinstance(item, dict) and isinstance(item.get("n"), int) and 1 <= item["n"] <= len(group):
                shots[group[item["n"] - 1]]["desc"] = " ".join(str(item.get("desc") or "").split())[:160]


def scene_seconds(scenes: list[dict], total: float) -> list[float]:
    """Expected length of each scene: the narration time shared by the scene's words."""
    words = [max(1, len(scene["text"].split())) for scene in scenes]
    return [total * count / sum(words) for count in words]


_ASSIGN_SCHEMA = {
    "type": "object",
    "properties": {"assignments": {"type": "array", "items": {
        "type": "object", "properties": {"scene": {"type": "integer"}, "shot": {"type": "integer"}},
        "required": ["scene", "shot"]}}},
    "required": ["assignments"],
}


def assign_shots(provider: BaseAIProvider, scenes: list[dict], shots: list[dict], total_seconds: float) -> tuple[list[int | None], list[str]]:
    """Shot index for each scene (None = no shot fits, the scene uses a picture); plus warnings for the user.

    The AI chooses by meaning; the code then enforces one scene per shot and fills gaps in story order.
    """
    lengths = scene_seconds(scenes, total_seconds)
    scene_lines = "\n".join(f"{index}. ({length:.0f}s) {scene['text'][:300]}"
                            for index, (scene, length) in enumerate(zip(scenes, lengths), 1))
    shot_lines = "\n".join(f"{index}. [bắt đầu {shot['start']:.0f}s] {shot.get('desc') or '(không rõ)'}"
                           for index, shot in enumerate(shots, 1))
    system = """Bạn là dựng phim cho video kiến thức dạng dọc. Mỗi cảnh (lời đọc) sẽ dùng 1 ĐOẠN LIỀN của video nguồn,
bắt đầu từ shot bạn chọn và chạy tiếp đủ số giây của cảnh (qua các shot liền sau nó).
- Chọn shot bắt đầu có hình ảnh khớp nhất với nội dung lời đọc của cảnh.
- Mỗi shot chỉ làm điểm bắt đầu cho 1 cảnh; các đoạn không nên chồng lên nhau, nên chọn shot bắt đầu cách xa nhau
  đủ số giây. Ưu tiên giữ thứ tự thời gian của shot giống thứ tự cảnh khi có thể.
- Tránh shot chỉ có chữ, logo, màn hình tiêu đề hoặc người dẫn nói trước camera.
- Nếu không có shot nào hợp với cảnh, trả "shot": 0.
- Chỉ trả về JSON đúng schema, không giải thích.
Schema: {"assignments": [{"scene": 1, "shot": 12}]}"""
    user = (f"Các cảnh (số giây cần):\n{scene_lines}\n\nCác shot có trong video nguồn (thời điểm bắt đầu, mô tả):\n"
            f"{shot_lines}")
    data = provider.generate_json(system, user, _ASSIGN_SCHEMA, temperature=0.2)
    chosen: list[int | None] = [None] * len(scenes)
    said_none: set[int] = set()
    used: set[int] = set()
    for item in data.get("assignments") or []:
        if not isinstance(item, dict):
            continue
        scene, shot = item.get("scene"), item.get("shot")
        if not isinstance(scene, int) or not 1 <= scene <= len(scenes) or chosen[scene - 1] is not None:
            continue
        if shot == 0:
            said_none.add(scene - 1)
        elif isinstance(shot, int) and 1 <= shot <= len(shots) and shot - 1 not in used:
            chosen[scene - 1] = shot - 1
            used.add(shot - 1)
    warnings = []
    ai_chose = len(used)
    # A small model sometimes answers "no fit" for most scenes; footage in story order is then better than pictures.
    if len(said_none) > len(scenes) // 2:
        warnings.append("AI không ghép được phần lớn cảnh; đã xếp shot theo thứ tự video — nên kiểm tra từng cảnh.")
        said_none = set()
    for index in range(len(scenes)):
        if chosen[index] is not None or index in said_none:
            continue
        after = max((chosen[earlier] for earlier in range(index) if chosen[earlier] is not None), default=-1)
        free = [shot for shot in range(len(shots)) if shot not in used]
        if not free:
            break
        pick = next((shot for shot in free if shot > after), free[0])
        chosen[index] = pick
        used.add(pick)
    missing = [str(index + 1) for index, shot in enumerate(chosen) if shot is None]
    if missing:
        warnings.append(f"Cảnh {', '.join(missing)}: không có shot hợp, sẽ dùng ảnh thay.")
    logger.info("clip_assign ai_chose=%d filled_in_order=%d no_shot=%d | %s", ai_chose, len(used) - ai_chose,
                len(missing), ", ".join(f"cảnh {index + 1}→shot {shot + 1}" if shot is not None else f"cảnh {index + 1}→ảnh"
                                        for index, shot in enumerate(chosen)))
    return chosen, warnings


# Each segment runs a little past its scene: the transition into the next scene overlaps it (0.6 s) and the
# scene length is only estimated before the render measures the voice.
SEGMENT_MARGIN = 1.0


def segment_needs(scenes: list[dict], total_seconds: float) -> list[float]:
    return [length + SEGMENT_MARGIN for length in scene_seconds(scenes, total_seconds)]


def segment_from(source: dict, shot_index: int, need: float) -> dict:
    """The continuous part of the source a scene uses: from the start of a shot, `need` seconds long
    (shorter only at the very end of the video)."""
    shot = source["shots"][shot_index]
    start = shot["start"]
    end = min(source["duration"] - 0.2, start + need)
    return {"shot": shot_index, "thumb": shot["thumb"], "start": round(start, 3), "end": round(max(start + 0.5, end), 3)}


def overlapping(clips: list[dict | None], index: int) -> list[int]:
    """Other scenes whose segment overlaps scene `index`'s segment."""
    clip = clips[index]
    if not clip or "start" not in clip:
        return []
    return [other for other, item in enumerate(clips) if other != index and item and "start" in item
            and clip["start"] < item["end"] and item["start"] < clip["end"]]


def plan_segments(source: dict, chosen: list[int | None], needs: list[float]) -> tuple[list[dict | None], list[str]]:
    """Turn the chosen start shots into non-overlapping continuous segments.

    A segment that would overlap one already placed starts at the next shot that leaves room (searching forward,
    then from the beginning); when the video is too short for it the scene uses a picture.
    """
    shots, placed, clips, moved, missing = source["shots"], [], [], [], []
    for index, pick in enumerate(chosen):
        if pick is None:
            clips.append(None)
            continue
        found = None
        for candidate in list(range(pick, len(shots))) + list(range(0, pick)):
            segment = segment_from(source, candidate, needs[index])
            # Too close to the end: the clip would have to be slowed down beyond MAX_SLOWDOWN.
            if (segment["end"] - segment["start"]) * MAX_SLOWDOWN < needs[index] - SEGMENT_MARGIN:
                continue
            if any(segment["start"] < end and start < segment["end"] for start, end in placed):
                continue
            found = segment
            break
        if found is None:
            missing.append(str(index + 1))
            clips.append(None)
            continue
        if found["shot"] != pick:
            moved.append(str(index + 1))
        placed.append((found["start"], found["end"]))
        clips.append(found)
    warnings = []
    if moved:
        warnings.append(f"Cảnh {', '.join(moved)}: đoạn AI chọn trùng với cảnh khác, đã dời sang đoạn trống gần nhất.")
    if missing:
        warnings.append(f"Cảnh {', '.join(missing)}: video nguồn không còn đoạn trống đủ dài, sẽ dùng ảnh thay. "
                        "Chọn video nguồn dài hơn hoặc giảm số cảnh.")
    logger.info("clip_segments %s", ", ".join(
        f"cảnh {index + 1}: {clip['start']:.1f}-{clip['end']:.1f}s" if clip else f"cảnh {index + 1}: ảnh"
        for index, clip in enumerate(clips)))
    return clips, warnings


def assign_segments(provider: BaseAIProvider, scenes: list[dict], source: dict,
                    total_seconds: float) -> tuple[list[dict | None], list[str]]:
    """AI picks the start shot of each scene by meaning; the code lays out continuous segments."""
    chosen, warnings = assign_shots(provider, scenes, source["shots"], total_seconds)
    clips, more = plan_segments(source, chosen, segment_needs(scenes, total_seconds))
    return clips, warnings + more


# ---------- cutting the scene clips at render time ----------

def _overlaps(box: tuple[int, int, int, int], window: tuple[int, int, int, int]) -> bool:
    x, y, w, h = box
    wx, wy, ww, wh = window
    return x < wx + ww and wx < x + w and y < wy + wh and wy < y + h


def crop_plan(width: int, height: int, target_w: int, target_h: int,
              logos: list[list[float]]) -> tuple[tuple[int, int, int, int], list[tuple[int, int, int, int]]]:
    """Crop window with the target aspect that avoids the logos when it can (closest to centre), and the logo
    boxes still inside it (in window coordinates), which get blurred."""
    aspect = target_w / target_h
    if width / height > aspect:
        crop_w, crop_h = int(height * aspect) // 2 * 2, height // 2 * 2
    else:
        crop_w, crop_h = width // 2 * 2, int(width / aspect) // 2 * 2
    boxes = [(int(x * width), int(y * height), math.ceil(w * width), math.ceil(h * height)) for x, y, w, h in logos]
    free_x, free_y = width - crop_w, height - crop_h
    centre = (free_x // 2, free_y // 2)
    positions = sorted({(round(free_x * step / 40), round(free_y * step / 40)) for step in range(41)}
                       if free_x or free_y else {(0, 0)},
                       key=lambda point: abs(point[0] - centre[0]) + abs(point[1] - centre[1]))
    window = next(((x, y, crop_w, crop_h) for x, y in positions
                   if not any(_overlaps(box, (x, y, crop_w, crop_h)) for box in boxes)), None)
    if window:
        return window, []
    window = (centre[0], centre[1], crop_w, crop_h)
    inside = []
    for x, y, w, h in boxes:
        if not _overlaps((x, y, w, h), window):
            continue
        left, top = max(x, window[0]) - window[0], max(y, window[1]) - window[1]
        right, bottom = min(x + w, window[0] + crop_w) - window[0], min(y + h, window[1] + crop_h) - window[1]
        if right - left >= 4 and bottom - top >= 4:
            inside.append((left // 2 * 2, top // 2 * 2, (right - left) // 2 * 2, (bottom - top) // 2 * 2))
    return window, inside


def _clip_filter(window, blurs, target_w: int, target_h: int, slowdown: float) -> str:
    x, y, w, h = window
    chain = [f"[0:v]crop={w}:{h}:{x}:{y},setsar=1[c0]"]
    label = "c0"
    for index, (bx, by, bw, bh) in enumerate(blurs):
        chain.append(f"[{label}]split[b{index}a][b{index}b]")
        chain.append(f"[b{index}b]crop={bw}:{bh}:{bx}:{by},gblur=sigma=18[b{index}c]")
        chain.append(f"[b{index}a][b{index}c]overlay={bx}:{by}[c{index + 1}]")
        label = f"c{index + 1}"
    chain.append(f"[{label}]scale={target_w}:{target_h}:flags=lanczos,setpts={slowdown:.4f}*PTS,fps=30,"
                 "format=yuv420p[out]")
    return ";".join(chain)


def cut_scene_clip(source: dict, shot: dict, needed: float, target_w: int, target_h: int, output: Path) -> dict:
    """Fetch one time range {"start", "end"} in high quality (only that range) and make the scene clip: 9:16, logos
    avoided or blurred, no sound, slowed down a little when the range is shorter than the scene."""
    directory = output.parent
    stem = output.stem + "_src"
    for stale in directory.glob(stem + ".*"):
        stale.unlink(missing_ok=True)
    check_cancelled()
    _download(source["id"], {
        "format": "bv*[height<=1080][ext=mp4]/bv*[height<=1080]",
        "download_ranges": yt_dlp.utils.download_range_func(None, [(shot["start"], shot["end"])]),
        "force_keyframes_at_cuts": True,
        "outtmpl": str(directory / f"{stem}.%(ext)s"),
    })
    check_cancelled()
    downloaded = [path for path in directory.glob(stem + ".*") if not path.name.endswith(".part")]
    if not downloaded:
        raise ClipError(f"Không tải được đoạn {shot['start']:.1f}-{shot['end']:.1f}s của video nguồn.")
    raw = downloaded[0]
    try:
        stream = next(item for item in probe(raw)["streams"] if item.get("codec_type") == "video")
        window, blurs = crop_plan(int(stream["width"]), int(stream["height"]), target_w, target_h, source.get("logos") or [])
        length = max(0.1, shot["end"] - shot["start"])
        slowdown = min(MAX_SLOWDOWN, max(1.0, needed / length))
        run_media(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", raw.name, "-filter_complex",
                   _clip_filter(window, blurs, target_w, target_h, slowdown), "-map", "[out]", "-an",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", output.name], directory, 600)
    finally:
        raw.unlink(missing_ok=True)
    return {"file": output.name, "blurred": len(blurs), "slowdown": round(slowdown, 2)}


def prepare_render_clips(state: dict, assets: Path, resolution: str, total_seconds: float, progress) -> None:
    """Cut the clip of every scene that uses a shot (scene["clip"]["file"]); scenes on a picture are left alone."""
    source = state["clip_source"]
    target_w, target_h = map(int, resolution.split("x"))
    scenes = state["scenes"]
    needs = segment_needs(scenes, total_seconds)
    todo = [index for index, scene in enumerate(scenes) if scene.get("clip")]
    for number, index in enumerate(todo, 1):
        progress("prepare_clips", round(2 + 8 * (number - 1) / max(1, len(todo))))
        clip = scenes[index]["clip"]
        # Scenes matched before segments existed hold only a shot: they use that shot's own range.
        shot = source["shots"][clip["shot"]]
        span = {"start": clip.get("start", shot["start"]), "end": clip.get("end", shot["end"])}
        output = assets / f"scene_{index:02d}_clip_{target_h}.mp4"
        cut_key = [source["id"], span["start"], span["end"], source.get("logos") or []]
        # Reused when the same range was already cut the same way (e.g. re-rendering with another template).
        if clip.get("file") == output.name and clip.get("cut_key") == cut_key and output.is_file():
            continue
        clip.pop("file", None)
        started = time.monotonic()
        result = cut_scene_clip(source, span, needs[index], target_w, target_h, output)
        clip.update({**result, "cut_key": cut_key})
        logger.info("scene_clip index=%d range=%.1f-%.1fs took=%.1fs blurred=%d", index, span["start"], span["end"],
                    time.monotonic() - started, result["blurred"])


def release_source(source: dict) -> None:
    """After a successful render the 360p analysis copy is no longer needed (downloaded again if shots change)."""
    for path in cache_directory().glob(f"{source['id']}_360.*"):
        path.unlink(missing_ok=True)


def write_credits(state: dict, directory: Path) -> Path | None:
    source = state.get("clip_source")
    path = directory / "credits.txt"
    if not source or not any(scene.get("clip") for scene in state.get("scenes") or []):
        path.unlink(missing_ok=True)
        return None
    path.write_text("Nguồn video: " + credit_line(source) + "\n", encoding="utf-8")
    return path


def estimated_total(state: dict) -> float:
    return float(((state.get("script") or {}).get("timing") or {}).get("seconds") or state.get("duration") or 60)

