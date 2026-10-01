"""Short low-resolution previews of a template and its scene transitions.

They reuse the render's per-scene filter, grade, title card, transition joins and (optionally) Ken Burns motion, so
what is previewed is what the final video shows, minus subtitles and voice.
"""
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core import samples
from core.config import RunStore
from core.render import _content_label, _year_badge
from core.title_cards import HISTORY_GRADES, HISTORY_TEMPLATES, render_title_card
from core.video_pipeline import (
    TRANSITION_SECONDS, join_scenes, render_motion_scene, run_media, scene_look, transition_names,
)

WIDTH, HEIGHT = 360, 640
SCENE_SECONDS = 2.2
CARD_SECONDS = 1.4
SCENES = 3
# Part of every cache key: raised when the title cards are redrawn so old previews are not shown.
_VERSION = 2


@dataclass
class PreviewSource:
    """Pictures and title card texts a preview is built from, and where its files are cached."""
    images: list[Path]
    title: str
    badge: str
    label: str
    cache: Path
    origin: str = ""


def _repeat(images: list[Path], count: int) -> list[Path]:
    return [images[index % len(images)] for index in range(count)]


def scene_picture(directory: Path, scene: dict) -> Path | None:
    """Still picture of a scene: the frame of its shot (clip flow) or its image."""
    clip, image = scene.get("clip"), scene.get("image")
    if clip and clip.get("thumb"):
        return directory / "assets" / "clip_shots" / clip["thumb"]
    return directory / "assets" / image["file"] if image else None


def _run_images(directory: Path, state: dict) -> list[Path]:
    paths = [scene_picture(directory, scene) for scene in state.get("scenes") or []]
    return [path for path in paths if path and path.is_file()]


def run_source(store: RunStore, state: dict, count: int = SCENES) -> PreviewSource:
    """The video being made: its own scene images and title."""
    images = _run_images(store.directory, state)
    if not images:
        raise RuntimeError("Chưa có ảnh cảnh nào để xem trước.")
    title = (state.get("script") or {}).get("title") or state.get("topic") or ""
    return PreviewSource(_repeat(images[:count], count), title, _year_badge(title, state.get("topic", "")),
                         _content_label(state), store.directory / "preview")


def gallery_source(count: int = SCENES) -> PreviewSource:
    """For the template gallery: always the plain sample pictures, cached in the system temp folder (not output/)."""
    cache = Path(tempfile.gettempdir()) / "KnowledgeVideo" / "preview"
    images = samples.sample_images(cache / "samples")
    return PreviewSource(_repeat(images, count), samples.TITLE, _year_badge(samples.TITLE), "Kiến thức lịch sử",
                         cache, "ảnh minh họa mẫu")


def _cache_path(source: PreviewSource, suffix: str, *parts: str) -> Path:
    key_parts = [str(_VERSION), *parts, source.title, source.badge, source.label]
    key_parts += [f"{path}:{path.stat().st_mtime_ns}" for path in source.images]
    key = hashlib.sha1("|".join(key_parts).encode("utf-8")).hexdigest()[:16]
    source.cache.mkdir(parents=True, exist_ok=True)
    return source.cache / f"{key}{suffix}"


def render_thumbnail(source: PreviewSource, template: str) -> Path:
    """First frame of the video for this template: scene 1 with the template's grade and title card."""
    output = _cache_path(source, ".jpg", "thumb", template)
    if output.is_file():
        return output
    command = ["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(source.images[0])]
    video = f"[0:v]{scene_look(WIDTH, HEIGHT, HISTORY_GRADES.get(template, ''))}setsar=1"
    if template in HISTORY_TEMPLATES:
        card = render_title_card(template, source.title, source.badge, source.label, WIDTH, HEIGHT,
                                 output.with_suffix(".png"))
        command += ["-i", str(card)]
        video += "[scene];[1:v]format=rgba[card];[scene][card]overlay=x=0:y=0"
    temporary = output.with_name(output.stem + ".tmp.jpg")
    command += ["-filter_complex", video + "[out]", "-map", "[out]", "-frames:v", "1", "-q:v", "3", str(temporary)]
    run_media(command, output.parent, timeout=30)
    temporary.replace(output)
    return output


def render_preview(source: PreviewSource, template: str, transition: str, motion: bool = False) -> Path:
    """Clip of SCENES scenes: title card over the first, then the chosen transitions (and Ken Burns if `motion`)."""
    output = _cache_path(source, ".mp4", template, transition, "motion" if motion else "still")
    if output.is_file():
        return output
    directory, key = output.parent, output.stem
    names = transition_names(template, transition, SCENES - 1)
    overlap = 0.0 if names[0] == "none" else TRANSITION_SECONDS
    total = SCENES * SCENE_SECONDS
    grade = HISTORY_GRADES.get(template, "")
    command = ["ffmpeg", "-y", "-nostdin", "-v", "error"]
    filters = []
    for index, path in enumerate(source.images[:SCENES]):
        length = SCENE_SECONDS + (overlap if index < SCENES - 1 else 0.0)
        if motion:
            clip = directory / f"{key}_motion{index}.mp4"
            render_motion_scene(path, clip, WIDTH, HEIGHT, length, index)
            command += ["-i", str(clip)]
        else:
            command += ["-loop", "1", "-framerate", "30", "-t", f"{length:.3f}", "-i", str(path)]
        filters.append(
            f"[{index}:v]{scene_look(WIDTH, HEIGHT, grade)}setsar=1,trim=duration={length:.3f},"
            f"setpts=PTS-STARTPTS,format=yuv420p,settb=AVTB[scene{index}]"
        )
    filters += join_scenes(SCENES, [index * SCENE_SECONDS for index in range(SCENES)], names, overlap)
    if template in HISTORY_TEMPLATES:
        card = render_title_card(template, source.title, source.badge, source.label, WIDTH, HEIGHT,
                                 directory / f"{key}_card.png")
        command += ["-loop", "1", "-framerate", "30", "-t", f"{total:.3f}", "-i", str(card)]
        filters += [
            f"[{SCENES}:v]format=rgba[card]",
            f"[joined][card]overlay=x=0:y=0:eof_action=repeat:enable='lt(t,{CARD_SECONDS})'[video]",
        ]
    else:
        filters.append("[joined]null[video]")
    temporary = directory / f"{key}.tmp.mp4"
    command += ["-filter_complex", ";".join(filters), "-map", "[video]", "-t", f"{total:.3f}", "-an",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(temporary)]
    run_media(command, directory, timeout=60)
    temporary.replace(output)
    for index in range(SCENES):
        (directory / f"{key}_motion{index}.mp4").unlink(missing_ok=True)
    return output
