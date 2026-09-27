import re
import shutil
from pathlib import Path

from core import catalog
from core.config import RunStore
from core.video_pipeline import render


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
    sources = {(scene.get("image") or {}).get("source") for scene in scenes}
    labels = []
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


def build_snapshot(state: dict, render_options: dict, music_file: str, tts_rate: str = "+0%") -> dict:
    scenes = state["scenes"]
    missing = [index + 1 for index, scene in enumerate(scenes) if not scene.get("image")]
    if missing:
        raise RuntimeError(f"Các cảnh chưa có ảnh: {', '.join(map(str, missing))}.")
    script = state["script"]
    return {
        "script": {"title": script["title"], "hook": script["hook"], "body": script["body"], "revision": 1},
        "voice": render_options["voice"],
        "tts_rate": tts_rate,
        "resolution": render_options["resolution"],
        "template": render_options["template"],
        "video_mode": "news_report",
        "asset_files": [scene["image"]["file"] for scene in scenes],
        "music_file": music_file,
        "music_volume": render_options["music_volume"],
        "source_name": _source_label(scenes),
        "title_badge": _year_badge(script["title"], state.get("topic", "")),
        "title_label": _content_label(state),
        "template_options": {"show_source": True, "show_title_card": True, "title_position": "top"},
    }


def render_video(store: RunStore, snapshot: dict, stage) -> Path:
    render(snapshot, store.render, store.directory, stage)
    return store.render / "final.mp4"
