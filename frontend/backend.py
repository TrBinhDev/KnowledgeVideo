"""Line-delimited JSON bridge between Electron and the existing Python core.

Only one long job runs at once. The input loop stays responsive so Cancel can stop ffmpeg and helper threads.
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import catalog, clips, images, sources, steps, timing, video_pipeline  # noqa: E402
from core.ai import build_provider, default_model, list_models  # noqa: E402
from core.config import RunStore, list_runs, output_directory, setup_logging  # noqa: E402
from core.preview import gallery_source, render_preview, render_thumbnail, run_source  # noqa: E402
from core.render import build_snapshot, export_video, import_music, render_video  # noqa: E402

setup_logging()
logger = logging.getLogger("kv.frontend")
_write_lock = threading.Lock()
_job_lock = threading.Lock()
_job_thread: threading.Thread | None = None
_job_ident: int | None = None

SETTING_KEYS = (
    "KV_GEMINI_API_KEY", "KV_GEMINI_MODEL", "KV_GEMINI_IMAGE_MODEL", "KV_GATEWAY_API_KEY",
    "KV_GATEWAY_BASE_URL", "KV_GATEWAY_MODEL", "KV_OLLAMA_URL", "KV_OLLAMA_MODEL",
    "KV_OLLAMA_TIMEOUT_SECONDS", "KV_VISION_MODEL", "KV_OUTPUT_DIR", "KV_CLIP_CACHE_MB",
    "KV_HTTP_USER_AGENT", "KV_VIDEO_FONT",
)


def send(value: dict) -> None:
    encoded = json.dumps(value, ensure_ascii=True, default=str)
    with _write_lock:
        if len(encoded) > 3000:
            for offset in range(0, len(encoded), 3000):
                part = encoded[offset:offset + 3000]
                sys.stdout.write(json.dumps({"type": "chunk", "id": value.get("id"), "data": part,
                                             "last": offset + 3000 >= len(encoded)}) + "\n")
        else:
            sys.stdout.write(encoded + "\n")
        sys.stdout.flush()


def progress(label: str, percent: int = -1) -> None:
    video_pipeline.check_cancelled()
    send({"type": "progress", "label": str(label), "percent": int(percent)})


def provider(params: dict):
    name = params.get("provider") or "ollama"
    model = params.get("model") or default_model(name)
    built = build_provider(name, model, params.get("fallback_models") or [])
    built.notify = progress
    return built


def vision_provider(params: dict):
    choice = params.get("vision") or "same"
    name = params.get("provider") if choice == "same" else choice
    if name == "ollama":
        return clips.ollama_vision
    selected = provider({**params, "provider": name, "model": params.get("model") if choice == "same" else None})
    return clips.gemini_vision(selected)


def saved_run(params: dict) -> tuple[RunStore, dict]:
    directory = Path(str(params.get("directory") or "")).resolve()
    root = output_directory().resolve()
    if directory == root or root not in directory.parents:
        raise ValueError("Thư mục video không thuộc thư mục output.")
    state = params.get("state")
    if not isinstance(state, dict):
        state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    return RunStore(directory), state


def persist(store: RunStore, state: dict) -> dict:
    store.save(state)
    return {"directory": str(store.directory), "state": state}


def runs() -> list[dict]:
    summaries = []
    for directory, state in list_runs():
        scenes = state.get("scenes") or []
        first = scenes[0] if scenes else {}
        summaries.append({"directory": str(directory), "state": {
            "kind": state.get("kind"), "duration": state.get("duration"),
            "topic": state.get("topic"), "input": str(state.get("input") or "")[:120],
            "script": {"title": (state.get("script") or {}).get("title")},
            "scene_count": len(scenes), "scenes": [{"image": first.get("image"), "clip": first.get("clip")}] if first else [],
            "video": state.get("video"),
        }})
    return summaries


def image_path(store: RunStore, scene: dict) -> str:
    clip = scene.get("clip") or {}
    if clip.get("thumb"):
        return str(store.assets / "clip_shots" / clip["thumb"])
    image = scene.get("image") or {}
    return str(store.assets / image["file"]) if image.get("file") else ""


def catalog_data() -> dict:
    return {
        "voices": catalog.VOICES,
        "styles": {key: value[0] for key, value in catalog.STYLES.items()},
        "durations": catalog.DURATIONS,
        "scene_choices": catalog.SCENE_CHOICES,
        "point_counts": catalog.POINT_COUNTS,
        "templates": catalog.TEMPLATES_BY_TYPE["kien_thuc"],
        "transitions": catalog.TRANSITIONS,
        "scene_timings": catalog.SCENE_TIMINGS,
        "subtitle_styles": catalog.SUBTITLE_STYLES,
        "resolutions": catalog.RESOLUTIONS,
        "clip_filters": {key: item[0] for key, item in clips.CONTENT_FILTERS.items()},
    }


def get_settings() -> dict:
    return {key: os.environ.get(key, "") for key in SETTING_KEYS}


def fill_images(store: RunStore, state: dict, missing_only: bool = True, pollinations: bool = True,
                fallback_only: bool = False) -> list[str]:
    scenes = state.get("scenes") or []
    topic = state.get("topic") or ""
    title = (state.get("script") or {}).get("title") or topic
    subject = state.get("image_subject") or {}
    warnings: list[str] = []
    pool = []
    if not fallback_only:
        try:
            pool = images.wikipedia_vi_pool(subject.get("vi") or topic)
        except (OSError, ValueError) as error:
            warnings.append(f"Không đọc được Wikipedia ({type(error).__name__}).")
    used = {(scene.get("image") or {}).get("url") for scene in scenes if (scene.get("image") or {}).get("url")}
    for index, scene in enumerate(scenes):
        video_pipeline.check_cancelled()
        if scene.get("clip"):
            continue
        if missing_only and (scene.get("image") or {}).get("source") not in (None, "placeholder"):
            continue
        progress(f"Tìm ảnh cảnh {index + 1}/{len(scenes)}", round(100 * index / max(1, len(scenes))))
        image, notes = images.fetch_scene_image(scene, store.assets, index, used, topic, title, pool,
                                                 pollinations and not fallback_only, subject)
        scene["image"] = image
        if image.get("url"):
            used.add(image["url"])
        warnings.extend(notes)
    progress("Đã chuẩn bị ảnh", 100)
    return warnings


def prepare_clip(store: RunStore, state: dict, video_id: str, ai, vision) -> tuple[dict, list[str]]:
    shots_dir = store.assets / "clip_shots"
    source = clips.prepare_source(video_id, shots_dir, progress)
    clips.describe_shots(source, shots_dir, progress, vision)
    chosen, notes = clips.assign_segments(ai, state["scenes"], source, clips.estimated_total(state))
    state["clip_source"] = source
    for scene, clip in zip(state["scenes"], chosen):
        scene["clip"] = clip
    notes.extend(fill_images(store, state, missing_only=True, pollinations=False, fallback_only=True))
    return source, notes


def render_current(store: RunStore, state: dict, options: dict) -> dict:
    state["render"] = options
    persist(store, state)
    script = state["script"]
    fitted = script.get("timing") or {}
    if fitted.get("voice") != options["voice"] or fitted.get("narration") != timing.narration(script):
        progress("Đo thời lượng với giọng đọc đã chọn", 2)
        fitted = timing.fit_rate(timing.narration(script), options["voice"], state["duration"], progress)
        script["timing"] = fitted
        persist(store, state)
    if state.get("kind") == "clip" and state.get("clip_source"):
        clips.prepare_render_clips(state, store.assets, options["resolution"], fitted["seconds"], progress)
        persist(store, state)
    snapshot = build_snapshot(state, options, import_music(store, options.get("music_source") or ""), fitted["tts_rate"])
    video = render_video(store, snapshot, progress)
    if state.get("kind") == "clip" and state.get("clip_source"):
        clips.write_credits(state, video.parent)
        clips.release_source(state["clip_source"])
    state["video"] = str(video)
    persist(store, state)
    return {"directory": str(store.directory), "state": state, "video": str(video)}


def dispatch(method: str, params: dict):
    if method == "bootstrap":
        return {"catalog": catalog_data(), "settings": get_settings(), "runs": runs(),
                "output_dir": str(output_directory()), "cache_mb": round(clips.cache_size() / 1024 / 1024)}
    if method == "list_runs":
        return {"runs": runs(), "output_dir": str(output_directory())}
    if method == "open_run":
        store, state = saved_run(params)
        return {"directory": str(store.directory), "state": state}
    if method == "list_models":
        return {"models": list_models(params.get("provider") or "ollama")}
    if method == "settings":
        return {"settings": get_settings(), "cache_mb": round(clips.cache_size() / 1024 / 1024),
                "output_dir": str(output_directory())}
    if method == "save_settings":
        from core.config import update_env
        values = {key: str(value) for key, value in (params.get("values") or {}).items() if key in SETTING_KEYS}
        if values.get("KV_OLLAMA_URL") and not values["KV_OLLAMA_URL"].startswith(("http://", "https://")):
            raise ValueError("Ollama URL phải bắt đầu bằng http:// hoặc https://.")
        if values.get("KV_GATEWAY_BASE_URL") and not values["KV_GATEWAY_BASE_URL"].startswith("https://"):
            raise ValueError("Gateway URL phải bắt đầu bằng https://.")
        if values.get("KV_OLLAMA_TIMEOUT_SECONDS") and float(values["KV_OLLAMA_TIMEOUT_SECONDS"]) <= 0:
            raise ValueError("Ollama timeout phải lớn hơn 0.")
        if values.get("KV_CLIP_CACHE_MB") and int(values["KV_CLIP_CACHE_MB"]) < 200:
            raise ValueError("Giới hạn cache phải từ 200 MB.")
        font = values.get("KV_VIDEO_FONT")
        if font and (not Path(font).is_file() or Path(font).suffix.lower() not in (".ttf", ".otf")):
            raise ValueError("Font phải là file .ttf hoặc .otf có trên máy.")
        if values.get("KV_OUTPUT_DIR"):
            Path(values["KV_OUTPUT_DIR"]).expanduser().mkdir(parents=True, exist_ok=True)
        update_env(values)
        return {"settings": get_settings(), "output_dir": str(output_directory())}
    if method == "clear_cache":
        clips.clear_cache()
        return {"cache_mb": 0}
    if method == "load_document":
        path = Path(params["path"])
        if path.suffix.lower() == ".json":
            text, shortened = path.read_text(encoding="utf-8-sig"), False
        else:
            text, shortened = sources.limit(sources.read_document(path))
        return {"text": text, "shortened": shortened}
    if method == "parse_json":
        return steps.parse_script_json(params.get("text") or "")
    if method == "parse_source":
        return sources.split_narration(params.get("text") or "")
    if method == "suggest_topics":
        return {"topics": steps.suggest_topics(provider(params), "kien_thuc", "lich_su", params.get("input") or "")}
    if method == "create_run":
        state = dict(params.get("state") or {})
        topic = str(state.get("topic") or params.get("topic") or "video")
        state["topic"] = topic
        return persist(RunStore.create(topic), state)
    if method == "save_run":
        store, state = saved_run(params)
        return persist(store, state)
    if method == "make_outline":
        store, state = saved_run(params)
        state["outline"] = steps.make_outline(provider(params), "kien_thuc", "lich_su", state["topic"],
                                               int(state["duration"]), state.get("points"), state.get("style"),
                                               state.get("source") or "")
        return persist(store, state)
    if method == "update_outline":
        store, state = saved_run(params)
        points = steps.parse_outline_text(params.get("text") or "", int(state["duration"]))
        if not points:
            raise ValueError("Đề cương cần ít nhất một ý chính.")
        state["outline"] = {"title": params.get("title") or state["topic"], "points": points}
        return persist(store, state)
    if method == "write_script":
        store, state = saved_run(params)
        points = (state.get("outline") or {}).get("points") or []
        if not points:
            raise ValueError("Đề cương chưa có ý chính.")
        ai = provider(params)
        progress("AI viết lời đọc", 3)
        script = steps.write_script(ai, "kien_thuc", "lich_su", state["topic"],
                                    state["outline"].get("title") or state["topic"], points,
                                    state.get("style"), state.get("source") or "")
        state["script"] = steps.fit_script_duration(ai, "kien_thuc", "lich_su", script, int(state["duration"]),
                                                     state["voice"], progress, state.get("style"))
        return persist(store, state)
    if method == "fit_script":
        store, state = saved_run(params)
        state["script"] = steps.fit_script_duration(None, "", "", state["script"], int(state["duration"]),
                                                     state["voice"], progress)
        return persist(store, state)
    if method == "split_scenes":
        store, state = saved_run(params)
        script = state["script"]
        points = len((state.get("outline") or {}).get("points") or []) or steps.paragraph_count(script["body"])
        count = catalog.resolve_scene_count(state.get("scene_choice", "auto"), state["duration"], points)
        result = steps.split_scenes(provider(params), script["title"], state["topic"], script["hook"],
                                    script["body"], state["duration"], progress, count)
        state.update({"image_subject": result["subject"], "scenes": result["scenes"],
                      "video_query": result.get("video_query") or {}})
        return {**persist(store, state), "warnings": result.get("warnings") or []}
    if method == "fetch_images":
        store, state = saved_run(params)
        notes = fill_images(store, state, params.get("missing_only", True), params.get("pollinations", True))
        return {**persist(store, state), "warnings": notes}
    if method == "replace_image":
        store, state = saved_run(params)
        index = int(params["index"])
        scene = state["scenes"][index]
        variant = params.get("variant")
        used = {item.get("url") for item in (scene.get("seen_images") or []) if isinstance(item, dict)}
        used.update((item.get("image") or {}).get("url") for item in state["scenes"] if item.get("image"))
        if variant == "wikimedia":
            image = images.from_wikimedia(scene.get("image_query_vi") or scene.get("image_query_en") or state["topic"],
                                           store.assets, index, used)
            if not image:
                raise ValueError("Không tìm được ảnh Wikimedia khác. Hãy sửa từ khóa rồi thử lại.")
        elif variant == "pollinations":
            image = images.from_pollinations(scene.get("image_prompt") or scene["text"], store.assets, index)
        elif variant == "gemini":
            image = images.from_ai(scene.get("image_prompt") or scene["text"], store.assets, index)
        else:
            raise ValueError("Nguồn ảnh không hợp lệ.")
        scene.setdefault("seen_images", []).append(scene.get("image") or {})
        scene["image"] = image
        return persist(store, state)
    if method == "search_clips":
        found = clips.find_candidates(params.get("query") or "", params.get("filter") or "real", progress,
                                      vision=vision_provider(params), about=params.get("about") or "")
        return {"candidates": found}
    if method == "prepare_clips":
        store, state = saved_run(params)
        video_id = clips.youtube_id(params["video"])
        _, notes = prepare_clip(store, state, video_id, provider(params), vision_provider(params))
        return {**persist(store, state), "warnings": notes}
    if method == "reassign_clips":
        store, state = saved_run(params)
        chosen, notes = clips.assign_segments(provider(params), state["scenes"], state["clip_source"],
                                               clips.estimated_total(state))
        for scene, clip in zip(state["scenes"], chosen):
            scene["clip"] = clip
        notes.extend(fill_images(store, state, missing_only=True, pollinations=False, fallback_only=True))
        return {**persist(store, state), "warnings": notes}
    if method == "choose_shot":
        store, state = saved_run(params)
        index = int(params["index"])
        needs = clips.segment_needs(state["scenes"], clips.estimated_total(state))
        state["scenes"][index]["clip"] = clips.segment_from(state["clip_source"], int(params["shot"]), needs[index])
        overlaps = clips.overlapping([item.get("clip") for item in state["scenes"]], index)
        return {**persist(store, state), "warnings": [f"Đoạn trùng cảnh {', '.join(str(x + 1) for x in overlaps)}"] if overlaps else []}
    if method == "use_picture":
        store, state = saved_run(params)
        index = int(params["index"])
        state["scenes"][index]["clip"] = None
        notes = fill_images(store, state, missing_only=True, pollinations=False, fallback_only=True)
        return {**persist(store, state), "warnings": notes}
    if method == "set_logos":
        store, state = saved_run(params)
        boxes = params.get("logos") or []
        if not isinstance(boxes, list) or any(not isinstance(box, list) or len(box) != 4 or
                                              any(not isinstance(n, (float, int)) or n < 0 or n > 1 for n in box)
                                              for box in boxes):
            raise ValueError("Vùng logo phải là các tọa độ tỷ lệ từ 0 đến 1.")
        state["clip_source"]["logos"] = boxes
        state["clip_source"]["logos_from"] = "manual"
        return persist(store, state)
    if method == "render_preview":
        template = params.get("template") or "history-scroll"
        transition = params.get("transition") or "template"
        if params.get("directory"):
            store, state = saved_run(params)
            try:
                source = run_source(store, state)
            except RuntimeError:
                source = gallery_source()
        else:
            source = gallery_source()
        thumbnail = render_thumbnail(source, template)
        video = render_preview(source, template, transition, params.get("motion", True))
        return {"thumbnail": str(thumbnail), "video": str(video), "origin": source.origin}
    if method == "gallery":
        source = gallery_source()
        thumbnails = {key: str(render_thumbnail(source, key)) for key in catalog.TEMPLATES_BY_TYPE["kien_thuc"]}
        return {"thumbnails": thumbnails, "origin": source.origin}
    if method == "render_video":
        store, state = saved_run(params)
        return render_current(store, state, params["options"])
    if method == "auto_generate":
        store, state = saved_run(params)
        ai = provider(params)
        kind = state.get("kind") or "image"
        mode = state.get("mode") or "keywords"
        if not state.get("script"):
            if mode == "source_verbatim":
                state["script"] = sources.split_narration(state["source"])
                state["script"] = steps.fit_script_duration(None, "", "", state["script"], state["duration"],
                                                             state["voice"], progress)
            else:
                progress("AI lập đề cương", 4)
                state["outline"] = steps.make_outline(ai, "kien_thuc", "lich_su", state["topic"], state["duration"],
                                                       state.get("points"), state.get("style"), state.get("source") or "")
                persist(store, state)
                progress("AI viết kịch bản", 12)
                outline = state["outline"]
                script = steps.write_script(ai, "kien_thuc", "lich_su", state["topic"], outline["title"],
                                            outline["points"], state.get("style"), state.get("source") or "")
                state["script"] = steps.fit_script_duration(ai, "kien_thuc", "lich_su", script, state["duration"],
                                                             state["voice"], progress, state.get("style"))
            persist(store, state)
        if not state.get("scenes"):
            progress("AI chia cảnh", 30)
            script = state["script"]
            points = len((state.get("outline") or {}).get("points") or []) or steps.paragraph_count(script["body"])
            count = catalog.resolve_scene_count(state.get("scene_choice", "auto"), state["duration"], points)
            result = steps.split_scenes(ai, script["title"], state["topic"], script["hook"], script["body"],
                                        state["duration"], progress, count)
            state.update({"image_subject": result["subject"], "scenes": result["scenes"],
                          "video_query": result.get("video_query") or {}})
            persist(store, state)
        warnings = []
        if kind == "image":
            progress("Tìm ảnh cho các cảnh", 45)
            warnings.extend(fill_images(store, state, True, params.get("pollinations", True)))
            persist(store, state)
        else:
            video = state.get("clip_link") or ""
            if not video:
                queries = [state.get("clip_query") or (state.get("video_query") or {}).get("vi") or state["topic"],
                           (state.get("video_query") or {}).get("en") or ""]
                candidates = []
                for query in dict.fromkeys(query for query in queries if query):
                    progress(f"Tìm video nguồn: {query}", 45)
                    candidates.extend(clips.find_candidates(query, state.get("clip_filter") or "real", progress,
                                                           vision=vision_provider(params), about=state["topic"]))
                    best = clips.best_candidate(candidates)
                    if best and best.get("score", 0) >= clips.GOOD_SCORE:
                        break
                unique = {item["id"]: item for item in candidates}
                state["clip_candidates"] = sorted(unique.values(), key=lambda item: (not item["allowed"], -item["score"]))
                persist(store, state)
                best = clips.best_candidate(state["clip_candidates"])
                if not best or best.get("score", 0) < clips.GOOD_SCORE:
                    raise ValueError("Không tìm được video nguồn đủ hợp. Mở lại dự án để chọn video hoặc dán link.")
                video = best["id"]
            progress("Phân tích video nguồn", 52)
            _, notes = prepare_clip(store, state, clips.youtube_id(video), ai, vision_provider(params))
            warnings.extend(notes)
            persist(store, state)
            weak = clips.WEAK_MATCH_WARNING in notes or sum(not item.get("clip") for item in state["scenes"]) > len(state["scenes"]) / 2
            if weak and not state.get("clip_link"):
                following = clips.best_candidate(state.get("clip_candidates") or [], {state["clip_source"]["id"]})
                if following and following.get("score", 0) >= clips.GOOD_SCORE:
                    _, notes = prepare_clip(store, state, following["id"], ai, vision_provider(params))
                    warnings.extend(notes)
                    persist(store, state)
        progress("Render video", 70)
        result = render_current(store, state, params["options"])
        result["warnings"] = warnings
        return result
    if method == "export_video":
        store, state = saved_run(params)
        video = Path(state.get("video") or "")
        if not video.is_file():
            raise ValueError("Video chưa được render.")
        return {"files": [str(path) for path in export_video(video, Path(params["target"]))]}
    if method == "get_credits":
        store, _ = saved_run(params)
        path = store.directory / "render" / "credits.txt"
        return {"text": path.read_text(encoding="utf-8") if path.is_file() else ""}
    raise ValueError(f"Tác vụ không hỗ trợ: {method}")


def execute(request: dict) -> None:
    global _job_ident, _job_thread
    request_id = request.get("id")
    _job_ident = threading.get_ident()
    try:
        result = dispatch(str(request.get("method") or ""), request.get("params") or {})
        response = {"id": request_id, "result": result}
    except Exception as error:
        logger.exception("frontend_action_failed method=%s", request.get("method"))
        response = {"id": request_id, "error": str(error) or type(error).__name__}
    finally:
        video_pipeline.clear_cancel(_job_ident)
        with _job_lock:
            _job_ident = None
            _job_thread = None
    send(response)


def main() -> None:
    global _job_thread
    # Qt painting with fonts (clip grids for the vision AI, title cards) aborts the whole process when no
    # QGuiApplication exists; the PySide app always had one, this bridge did not. Electron sets
    # QT_QPA_PLATFORM=offscreen, so no window is created.
    from PySide6.QtGui import QGuiApplication
    qt_application = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 (must stay alive)
    # Requests come on stdin, and this loop always has a read pending there. On Windows a child that inherits
    # the same pipe (ffmpeg checks it for key presses) then hangs forever: the final "-f null" check of every
    # render never returned. Read requests from a private copy and give fd 0 (inherited by ffmpeg, ffprobe,
    # yt-dlp) the null device instead.
    requests = io.TextIOWrapper(os.fdopen(os.dup(0), "rb", buffering=0), encoding="utf-8")
    null_input = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_input, 0)
    os.close(null_input)
    for line in requests:
        try:
            request = json.loads(line)
        except ValueError:
            continue
        if request.get("method") == "cancel":
            if _job_ident is not None:
                video_pipeline.cancel_thread(_job_ident)
            continue
        with _job_lock:
            if _job_thread is not None and _job_thread.is_alive():
                send({"id": request.get("id"), "error": "Một tác vụ khác đang chạy. Hãy đợi hoặc hủy tác vụ đó."})
                continue
            _job_thread = threading.Thread(target=execute, args=(request,), daemon=True)
            _job_thread.start()


if __name__ == "__main__":
    main()
