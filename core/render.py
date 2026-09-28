import re
import shutil
from pathlib import Path

from core import catalog
from core.config import RunStore
from core.video_pipeline import render, run_media


def _year_badge(*texts: str) -> str:
    """First standalone 3-4 digit number (a year such as 938 or 1288) in the title or topic, for the history card."""
    for text in texts:
        match = re.search(r"(?<!\d)(\d{3,4})(?!\d)", text or "")
        if match:
            return match.group(1)
    return ""


def _content_label(state: dict) -> str:
    try:
        kind = catalog.CONTENT_TYPES[state["content_type"]]
        return f"{kind['label']} {kind['categories'][state['category']]['label']}"
    except KeyError:
        return "Kiến thức lịch sử"


def _source_label(scenes: list[dict]) -> str:
    sources = {(scene.get("image") or {}).get("source") for scene in scenes if not scene.get("clip")}
    labels = ["video YouTube"] if any(scene.get("clip") for scene in scenes) else []
    if sources & {"wikipedia", "wikipedia_topic"}:
        labels.append("Wikipedia")
    if "wikimedia" in sources:
        labels.append("Wikimedia Commons")
    if "openverse" in sources:
        labels.append("Openverse")
    if sources & {"ai", "pollinations"}:
        labels.append("minh họa AI")
    # The pipeline prefixes this with "Nguồn: ".
    return ", ".join(labels) if labels else "Kiến thức lịch sử"


def import_music(store: RunStore, source: str) -> str:
    """Copy the chosen music file into the run folder so the snapshot is self-contained."""
    if not source:
        return ""
    path = Path(source)
    if path.suffix.lower() not in (".mp3", ".wav", ".m4a") or not path.is_file():
        raise RuntimeError("Nhạc nền phải là file MP3/WAV/M4A tồn tại trên máy.")
    target = store.music / f"music{path.suffix.lower()}"
    shutil.copyfile(path, target)
    return target.name


def _scene_asset(scene: dict) -> str:
    """The scene's cut clip (clip flow) or its picture."""
    clip = scene.get("clip") or {}
    return clip.get("file") or (scene.get("image") or {}).get("file", "")


def build_snapshot(state: dict, render_options: dict, music_file: str, tts_rate: str = "+0%") -> dict:
    scenes = state["scenes"]
    missing = [index + 1 for index, scene in enumerate(scenes) if not _scene_asset(scene)]
    if missing:
        raise RuntimeError(f"Các cảnh chưa có ảnh hoặc clip: {', '.join(map(str, missing))}.")
    script = state["script"]
    source_name = _source_label(scenes)
    clip_source = state.get("clip_source") or {}
    if clip_source.get("channel") and any(scene.get("clip") for scene in scenes):
        # On-screen credit for the source video (CC BY needs the author named).
        source_name = source_name.replace("video YouTube", f"{clip_source['channel']} (YouTube)")
    return {
        "script": {"title": script["title"], "hook": script["hook"], "body": script["body"], "revision": 1},
        "voice": render_options["voice"],
        "tts_rate": tts_rate,
        "resolution": render_options["resolution"],
        "template": render_options["template"],
        "transition": render_options.get("transition", "template"),
        "scene_timing": render_options.get("scene_timing", "even"),
        "subtitle_style": render_options.get("subtitle_style", "normal"),
        "video_mode": "news_report",
        "asset_files": [_scene_asset(scene) for scene in scenes],
        "scene_texts": [scene["text"] for scene in scenes],
        "music_file": music_file,
        "music_volume": render_options["music_volume"],
        "source_name": source_name,
        "title_badge": _year_badge(script["title"], state.get("topic", "")),
        "title_label": _content_label(state),
        # No "Nguồn: ..." line on the video: the credits go in the post caption (credits.txt, "Copy ghi nguồn").
        "template_options": {"show_source": False, "show_title_card": True, "title_position": "top"},
    }


def render_video(store: RunStore, snapshot: dict, stage) -> Path:
    render(snapshot, store.render, store.directory, stage)
    video = store.render / "final.mp4"
    make_thumbnail(video)
    return video


def make_thumbnail(video: Path) -> Path:
    """Cover image for publishing: the frame at 0.5 s, i.e. the title card over scene 1."""
    output = video.with_name("thumbnail.jpg")
    run_media(["ffmpeg", "-y", "-nostdin", "-v", "error", "-ss", "0.5", "-i", video.name,
               "-frames:v", "1", "-q:v", "2", output.name], video.parent, 60)
    return output


def export_video(video: Path, target: Path) -> list[Path]:
    """Copy the MP4 with its subtitles, cover image and source credits next to it, all named after the chosen file."""
    target = target.with_suffix(".mp4")
    copies = [(video, target), (video.with_name("subtitles.srt"), target.with_suffix(".srt")),
              (video.with_name("thumbnail.jpg"), target.with_suffix(".jpg")),
              (video.with_name("credits.txt"), target.with_suffix(".credits.txt"))]
    written = []
    for source, destination in copies:
        if source.is_file():
            shutil.copyfile(source, destination)
            written.append(destination)
    return written
