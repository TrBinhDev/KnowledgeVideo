import json
import logging
import re

from core import catalog, prompts, timing
from core.ai import BaseAIProvider, ProviderResponseError

logger = logging.getLogger("kv.steps")


def _clean(value) -> str:
    return " ".join(str(value or "").split()).strip()


def suggest_topics(provider: BaseAIProvider, content_type: str, category: str, user_input: str, count: int = 6) -> list[dict]:
    guidance = catalog.category_info(content_type, category)["guidance"]
    data = provider.generate_json(*prompts.suggest_topics(guidance, user_input, count), prompts.TOPICS_SCHEMA, temperature=0.8)
    topics = []
    for item in data.get("topics") or []:
        if isinstance(item, dict):
            title, angle = _clean(item.get("title")), _clean(item.get("angle"))
        else:
            title, angle = _clean(item), ""
        if title and title.casefold() not in {topic["title"].casefold() for topic in topics}:
            topics.append({"title": title[:200], "angle": angle[:300]})
    if not topics:
        raise ProviderResponseError("AI không gợi ý được chủ đề nào. Hãy thử lại hoặc đổi từ khóa.")
    return topics


MIN_POINT_SECONDS = 3
# Beyond this relative gap the speaking rate (±10%) cannot close it, so the AI rewrites the length first.
REWRITE_THRESHOLD = 0.08
MAX_REWRITES = 2


def normalize_seconds(seconds: list[int | None], total: int) -> list[int]:
    """Scale per-point seconds so they sum exactly to `total`; missing values share the leftover evenly."""
    count = len(seconds)
    known = [value for value in seconds if isinstance(value, int) and value > 0]
    fill = max(MIN_POINT_SECONDS, (total - sum(known)) // max(1, count - len(known))) if len(known) < count else 0
    raw = [value if isinstance(value, int) and value > 0 else fill for value in seconds]
    scale = total / max(1, sum(raw))
    scaled = [max(MIN_POINT_SECONDS, round(value * scale)) for value in raw]
    scaled[scaled.index(max(scaled))] += total - sum(scaled)
    return scaled


def outline_to_text(points: list[dict]) -> str:
    return "\n".join(f"{point['seconds']}s | {point['text']}" for point in points)


def parse_outline_text(text: str, total: int) -> list[dict]:
    """Read edited lines like '20s | nội dung' (the seconds part is optional) and rebalance to `total`."""
    parsed = []
    for line in text.splitlines():
        match = re.match(r"^\s*(\d+)\s*s?\s*\|\s*(.+)$", line)
        content = _clean(match.group(2) if match else line)
        if content:
            parsed.append((int(match.group(1)) if match else None, content))
    seconds = normalize_seconds([value for value, _ in parsed], total) if parsed else []
    return [{"text": content, "seconds": value} for (_, content), value in zip(parsed, seconds)]


def make_outline(provider: BaseAIProvider, content_type: str, category: str, topic: str, duration_seconds: int,
                 point_count: int | None = None, style: str | None = None, source: str = "") -> dict:
    """`point_count` None derives it from the duration; `source` restricts facts to that document."""
    guidance = catalog.category_info(content_type, category)["guidance"]
    point_count = point_count or catalog.outline_point_count(duration_seconds)
    data = provider.generate_json(*prompts.outline(guidance, topic, duration_seconds, point_count,
                                                   catalog.style_instruction(style), source), prompts.OUTLINE_SCHEMA)
    items = []
    for point in data.get("points") or []:
        text = _clean(point.get("text") if isinstance(point, dict) else point)
        seconds = point.get("seconds") if isinstance(point, dict) else None
        if text:
            items.append((seconds if isinstance(seconds, int) and not isinstance(seconds, bool) else None, text))
    if len(items) < 2:
        raise ProviderResponseError("Đề cương AI trả về quá ít ý. Hãy tạo lại.")
    # AI arithmetic is unreliable, so the budget is always rebalanced to the requested duration.
    seconds = normalize_seconds([value for value, _ in items], duration_seconds)
    return {"title": _clean(data.get("title")) or topic,
            "points": [{"text": text, "seconds": value} for (_, text), value in zip(items, seconds)]}


def _word_budget(points: list[dict]) -> tuple[int, list[int]]:
    total_words = round(sum(point["seconds"] for point in points) * catalog.WORDS_PER_SECOND)
    hook_words = 15
    share = (total_words - hook_words) / max(1, sum(point["seconds"] for point in points))
    return hook_words, [max(8, round(point["seconds"] * share)) for point in points]


def _paragraphs(value) -> list[str]:
    if isinstance(value, list):
        return [_clean(part) for part in value if _clean(part)]
    return [_clean(part) for part in str(value or "").split("\n") if _clean(part)]


def write_script(provider: BaseAIProvider, content_type: str, category: str, topic: str,
                 title: str, points: list[dict], style: str | None = None, source: str = "") -> dict:
    guidance = catalog.category_info(content_type, category)["guidance"]
    hook_words, paragraph_words = _word_budget(points)
    data = provider.generate_json(*prompts.script(guidance, topic, title, points, hook_words, paragraph_words,
                                                  catalog.style_instruction(style), source),
                                  prompts.SCRIPT_SCHEMA)
    paragraphs = _paragraphs(data.get("paragraphs") or data.get("body"))
    result = {"title": _clean(data.get("title")) or title, "hook": _clean(data.get("hook")), "body": "\n\n".join(paragraphs)}
    if not result["hook"] or not result["body"]:
        raise ProviderResponseError("Kịch bản AI trả về thiếu hook hoặc thân bài. Hãy viết lại.")
    return result


def adjust_length(provider: BaseAIProvider, content_type: str, category: str, script: dict, ratio: float,
                  style: str | None = None) -> dict:
    """Ask the AI to lengthen or shorten every paragraph by `ratio`, keeping facts and order."""
    guidance = catalog.category_info(content_type, category)["guidance"]
    paragraphs = _paragraphs(script["body"])
    targets = [max(5, round(len(text.split()) * ratio)) for text in paragraphs]
    data = provider.generate_json(*prompts.adjust_length(guidance, paragraphs, targets, catalog.style_instruction(style)),
                                  prompts.ADJUST_SCHEMA, temperature=0.4)
    rewritten = _paragraphs(data.get("paragraphs"))
    if len(rewritten) < max(1, len(paragraphs) // 2):
        raise ProviderResponseError("AI chỉnh độ dài kịch bản không hợp lệ. Hãy viết lại.")
    return {**script, "body": "\n\n".join(rewritten)}


def fit_script_duration(provider: BaseAIProvider | None, content_type: str, category: str, script: dict,
                        target_seconds: int, voice: str, progress=None, style: str | None = None) -> dict:
    """Measure real TTS length; if far off let the AI rewrite (when a provider is given), then tune the speaking rate.

    Passing provider=None keeps the text untouched (used after manual edits and before rendering).
    """
    def report(message: str) -> None:
        if progress:
            progress(message, -1)

    seconds = timing.measure(timing.narration(script), voice)
    report(f"Đo giọng đọc: {seconds:.1f}s / mục tiêu {target_seconds}s")
    for attempt in range(MAX_REWRITES if provider else 0):
        if abs(seconds / target_seconds - 1) <= REWRITE_THRESHOLD:
            break
        direction = "kéo dài" if seconds < target_seconds else "rút ngắn"
        report(f"AI {direction} kịch bản (lần {attempt + 1})")
        script = adjust_length(provider, content_type, category, script, target_seconds / seconds, style)
        seconds = timing.measure(timing.narration(script), voice)
        report(f"Đo lại: {seconds:.1f}s")
    fitted = timing.fit_rate(timing.narration(script), voice, target_seconds, progress, measured_seconds=seconds)
    return {**script, "timing": fitted}


def split_scenes(provider: BaseAIProvider, title: str, topic: str, hook: str, body: str,
                 duration_seconds: int) -> dict:
    """Returns {"subject": {"vi", "en"}, "scenes": [...]}; each scene carries Vietnamese and English image keywords."""
    count = catalog.scene_count(duration_seconds)
    data = provider.generate_json(*prompts.scenes(title, topic, f"{hook}\n\n{body}", count),
                                  prompts.SCENES_SCHEMA, temperature=0.4)
    subject = {"vi": _clean(data.get("subject_vi")), "en": _clean(data.get("subject_en"))}
    scenes = []
    for item in data.get("scenes") or []:
        if not isinstance(item, dict):
            continue
        text = _clean(item.get("text"))
        query_vi = _clean(item.get("image_query_vi"))
        query_en = _clean(item.get("image_query_en"))
        prompt = _clean(item.get("image_prompt"))
        if text:
            scenes.append({
                "text": text,
                "image_query_vi": query_vi or subject["vi"],
                "image_query_en": query_en or subject["en"] or title,
                "image_prompt": prompt or query_en or text,
                "image": None,
            })
    if len(scenes) < 2:
        raise ProviderResponseError("AI chia cảnh không hợp lệ. Hãy chia lại.")
    if len(scenes) != count:
        logger.info("scene_count_mismatch expected=%d got=%d", count, len(scenes))
    return {"subject": subject, "scenes": scenes}


class ScriptImportError(ValueError):
    pass


SCRIPT_JSON_EXAMPLE = """{
  "title": "Trận Bạch Đằng năm 938",
  "hook": "Một bãi cọc gỗ dưới lòng sông đã chấm dứt hơn một nghìn năm Bắc thuộc.",
  "paragraphs": ["Đoạn lời đọc 1...", "Đoạn lời đọc 2..."],
  "outline": [{"text": "Bối cảnh", "seconds": 15}],
  "scenes": [{"text": "Lời đọc của cảnh", "image_query_vi": "sông Bạch Đằng",
              "image_query_en": "Bach Dang river", "image_prompt": "..."}]
}"""


def parse_script_json(text: str) -> dict:
    """Script written elsewhere (e.g. pasted from a chat) as JSON.

    Needs "title", "hook" and "paragraphs" (list) or "body" (text); "outline" and "scenes" are optional.
    Returns {"script", "outline" (list or None), "scenes" (list or None), "subject"}.
    """
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    try:
        data = json.loads(fenced.group(1) if fenced else raw)
    except ValueError as error:
        raise ScriptImportError(f"JSON không hợp lệ ({error}).") from error
    if not isinstance(data, dict):
        raise ScriptImportError("JSON phải là một object {...}.")
    paragraphs = _paragraphs(data.get("paragraphs") if data.get("paragraphs") is not None else data.get("body"))
    script = {"title": _clean(data.get("title")), "hook": _clean(data.get("hook")), "body": "\n\n".join(paragraphs)}
    missing = [name for name, value in (("title", script["title"]), ("hook", script["hook"]),
                                        ("paragraphs/body", script["body"])) if not value]
    if missing:
        raise ScriptImportError(f"Thiếu trường: {', '.join(missing)}.")
    outline = None
    if data.get("outline"):
        outline = []
        for point in data["outline"]:
            content = _clean(point.get("text") if isinstance(point, dict) else point)
            seconds = point.get("seconds") if isinstance(point, dict) else None
            if content:
                outline.append({"text": content,
                                "seconds": seconds if isinstance(seconds, int) and not isinstance(seconds, bool) else None})
    nested = data["subject"] if isinstance(data.get("subject"), dict) else {}
    subject = {"vi": _clean(data.get("subject_vi") or nested.get("vi")),
               "en": _clean(data.get("subject_en") or nested.get("en"))}
    scenes = None
    if data.get("scenes"):
        scenes = []
        for item in data["scenes"]:
            if not isinstance(item, dict) or not _clean(item.get("text")):
                raise ScriptImportError("Mỗi cảnh cần có \"text\" (lời đọc của cảnh).")
            query_en = _clean(item.get("image_query_en"))
            scenes.append({
                "text": _clean(item["text"]),
                "image_query_vi": _clean(item.get("image_query_vi")) or subject["vi"],
                "image_query_en": query_en or subject["en"] or script["title"],
                "image_prompt": _clean(item.get("image_prompt")) or query_en or _clean(item["text"]),
                "image": None,
            })
        if len(scenes) < 2:
            raise ScriptImportError("Cần ít nhất 2 cảnh, hoặc bỏ trường \"scenes\" để AI tự chia cảnh.")
    return {"script": script, "outline": outline, "scenes": scenes, "subject": subject}


def word_count(text: str) -> int:
    return len((text or "").split())


def estimated_seconds(hook: str, body: str) -> int:
    return round((word_count(hook) + word_count(body)) / catalog.WORDS_PER_SECOND)
