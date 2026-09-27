import html
import json
import logging
import math
import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse

from core.ai import generate_image
from core.config import http_user_agent
from core.network_security import fetch_safe_bytes
from core.video_pipeline import probe

logger = logging.getLogger("kv.images")

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_WIKI_VI_API = "https://vi.wikipedia.org/w/api.php"
_OPENVERSE_API = "https://api.openverse.org/v1/images/"
_POLLINATIONS_URL = "https://image.pollinations.ai/prompt/"
_ALLOWED_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
_MIN_WIDTH = 600
_RETRY_AFTER_CAP = 10.0
# Third-party reports put anonymous Pollinations use at about one request per 15 seconds.
_POLLINATIONS_MIN_INTERVAL = 15.0
_AI_STYLE = (
    "Historical illustration, painterly realistic style, vertical 9:16 composition, "
    "no text, no letters, no watermark. Scene: "
)

_pollinations_lock = threading.Lock()
_pollinations_last_call = 0.0


class ImageError(Exception):
    pass


def _strip_html(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def _retry_after(error: HTTPError) -> float:
    try:
        return min(_RETRY_AFTER_CAP, max(1.0, float(error.headers.get("Retry-After", ""))))
    except (AttributeError, TypeError, ValueError):
        return 5.0


def _fetch(url: str, timeout: float = 30) -> bytes:
    """GET with one polite retry when the server answers 429 Too Many Requests."""
    for attempt in range(2):
        try:
            return fetch_safe_bytes(url, timeout=timeout, user_agent=http_user_agent())
        except HTTPError as error:
            if error.code != 429 or attempt:
                raise
            wait = _retry_after(error)
            logger.warning("rate_limited host=%s wait=%.0fs", urlparse(url).hostname, wait)
            time.sleep(wait)
    raise ImageError("unreachable")


def _get_json(url: str, params: dict) -> dict:
    return json.loads(_fetch(f"{url}?{urlencode(params)}", timeout=20).decode("utf-8"))


_IMAGEINFO = {
    "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata", "iiurlwidth": 1080,
    "iiextmetadatafilter": "LicenseShortName|Artist",
}


def _imageinfo_candidates(pages: list[dict]) -> list[dict]:
    candidates = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime", "")
        if mime not in _ALLOWED_MIME or int(info.get("width") or 0) < _MIN_WIDTH:
            continue
        meta = info.get("extmetadata") or {}
        candidates.append({
            "url": info.get("thumburl") or info.get("url"),
            "page": info.get("descriptionurl", ""),
            "title": page.get("title", ""),
            "suffix": _ALLOWED_MIME[mime],
            "license": _strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
            "artist": _strip_html((meta.get("Artist") or {}).get("value", ""))[:120],
        })
    return candidates


def wikimedia_candidates(query: str, limit: int = 10) -> list[dict]:
    """Search Wikimedia Commons files and return usable image candidates with credit data."""
    data = _get_json(_COMMONS_API, {"action": "query", "format": "json", "generator": "search",
                                    "gsrsearch": query, "gsrnamespace": 6, "gsrlimit": limit, **_IMAGEINFO})
    pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda page: page.get("index", 0))
    return _imageinfo_candidates(pages)


_STOPWORDS = {
    "và", "của", "các", "những", "một", "là", "trong", "với", "cho", "về", "từ", "đến", "tại", "năm", "thời",
    "the", "of", "and", "in", "a", "an", "to", "on", "at", "for",
}


def _terms(text: str) -> set[str]:
    return {word for word in re.findall(r"\w+", (text or "").casefold()) if word not in _STOPWORDS}


def is_relevant(article_title: str, query: str) -> bool:
    """Wikipedia search is fuzzy ("đốt lò" matched a Nazi book-burning article), so require most query terms
    in the article title, and reject a title whose year differs from the query's year."""
    wanted, have = _terms(query), _terms(article_title)
    if not wanted:
        return False
    years_wanted = {term for term in wanted if term.isdigit()}
    years_have = {term for term in have if term.isdigit()}
    if years_wanted and years_have and not years_wanted & years_have:
        return False
    return len(wanted & have) >= max(1, math.ceil(0.6 * len(wanted)))


def wikipedia_vi_pool(query: str, articles: int = 3) -> list[dict]:
    """Images of the Vietnamese Wikipedia articles matching `query` (only articles that pass is_relevant)."""
    search = _get_json(_WIKI_VI_API, {"action": "query", "format": "json", "generator": "search",
                                      "gsrsearch": query, "gsrlimit": articles, "prop": "images", "imlimit": 50})
    pages = sorted((search.get("query") or {}).get("pages", {}).values(), key=lambda page: page.get("index", 0))
    rejected = [page.get("title", "") for page in pages if not is_relevant(page.get("title", ""), query)]
    if rejected:
        logger.info("wikipedia_articles_rejected query=%s titles=%s", query, rejected)
    pages = [page for page in pages if is_relevant(page.get("title", ""), query)]
    titles = []
    for page in pages:
        for image in page.get("images") or []:
            title = image.get("title", "")
            if title.lower().endswith(_IMAGE_SUFFIXES) and title not in titles:
                titles.append(title)
    if not titles:
        return []
    data = _get_json(_WIKI_VI_API, {"action": "query", "format": "json", "titles": "|".join(titles[:50]), **_IMAGEINFO})
    query = data.get("query") or {}
    renamed = {item["from"]: item["to"] for item in query.get("normalized") or []}
    by_title = {page.get("title"): page for page in (query.get("pages") or {}).values()}
    ordered = [by_title.get(renamed.get(title, title)) for title in titles]
    return _imageinfo_candidates([page for page in ordered if page])


def openverse_candidates(query: str, limit: int = 10) -> list[dict]:
    data = _get_json(_OPENVERSE_API, {"q": query, "page_size": limit})
    candidates = []
    for item in data.get("results") or []:
        url = item.get("url") or ""
        if not url or int(item.get("width") or _MIN_WIDTH) < _MIN_WIDTH:
            continue
        suffix = Path(urlparse(url).path).suffix.lower()
        license_code = str(item.get("license") or "").lower()
        license_label = ("Public domain" if license_code in ("cc0", "pdm")
                         else f"CC {license_code.upper()} {item.get('license_version') or ''}".strip())
        candidates.append({
            "url": url,
            "page": item.get("foreign_landing_url") or "",
            "title": item.get("title") or "",
            "suffix": suffix if suffix in _IMAGE_SUFFIXES else ".jpg",
            "license": license_label if license_code else "",
            "artist": str(item.get("creator") or "")[:120],
        })
    return candidates


def _is_image(path: Path) -> bool:
    try:
        return any(stream.get("codec_type") == "video" for stream in probe(path).get("streams", []))
    except (RuntimeError, ValueError, OSError):
        return False


def _save(content: bytes, target: Path) -> bool:
    target.write_bytes(content)
    if _is_image(target):
        return True
    target.unlink(missing_ok=True)
    return False


def _download_first(candidates: list[dict], assets_dir: Path, index: int, used_urls: set[str],
                    source: str, tag: str) -> dict | None:
    for candidate in candidates:
        if candidate["url"] in used_urls:
            continue
        target = assets_dir / f"scene_{index:02d}_{tag}{candidate['suffix']}"
        try:
            if _save(_fetch(candidate["url"]), target):
                credit = ", ".join(part for part in (candidate["artist"], candidate["license"]) if part)
                return {"file": target.name, "source": source, "url": candidate["url"],
                        "page": candidate["page"], "credit": credit or candidate["title"]}
        except (OSError, ValueError) as error:
            logger.warning("%s_download_failed url=%s error=%s code=%s",
                           source, candidate["url"], type(error).__name__, getattr(error, "code", ""))
    return None


def _query_variants(query: str) -> list[str]:
    """Keyword search requires every term to match, so long AI keyword lists often return nothing."""
    parts = [part.strip() for part in query.split(",") if part.strip()]
    variants = [query, ", ".join(parts[:2]), parts[0] if parts else ""]
    return [variant for index, variant in enumerate(variants) if variant and variant not in variants[:index]]


def _folded_terms(text: str) -> set[str]:
    """Terms without Vietnamese diacritics, so 'Hiến pháp' matches a file named 'Hien_phap_1946.jpg'."""
    folded = unicodedata.normalize("NFKD", (text or "").replace("đ", "d").replace("Đ", "D"))
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    # Bare numbers ("12", "2022") appear in many unrelated file names, so they never count as a match.
    return {term for term in _terms(folded.replace("_", " ")) if len(term) > 1 and not term.isdigit()}


def _mentions_query(candidate: dict, query: str) -> bool:
    """Keyword search on Commons/Openverse is loose (a 'Hanoi citizens' search returned a beauty-queen portrait);
    keep only files whose title shares at least one meaningful term with the query."""
    title = re.sub(r"^(file|tập tin):", "", candidate.get("title", ""), flags=re.IGNORECASE)
    return bool(_folded_terms(query) & _folded_terms(title))


def _search_download(finder, source: str, tag: str, query: str, assets_dir: Path, index: int,
                     used_urls: set[str]) -> dict | None:
    for variant in _query_variants(query):
        try:
            candidates = [item for item in finder(variant) if _mentions_query(item, variant)]
        except (OSError, ValueError) as error:
            logger.warning("%s_search_failed query=%s error=%s code=%s",
                           source, variant, type(error).__name__, getattr(error, "code", ""))
            return None
        image = _download_first(candidates, assets_dir, index, used_urls, source, tag)
        if image:
            return image
    return None


def from_wikimedia(query: str, assets_dir: Path, index: int, used_urls: set[str]) -> dict | None:
    return _search_download(wikimedia_candidates, "wikimedia", "wiki", query, assets_dir, index, used_urls)


def from_openverse(query: str, assets_dir: Path, index: int, used_urls: set[str]) -> dict | None:
    return _search_download(openverse_candidates, "openverse", "openverse", query, assets_dir, index, used_urls)


def from_wikipedia_pool(pool: list[dict], assets_dir: Path, index: int, used_urls: set[str]) -> dict | None:
    """Topic-wide pool: images are handed out in order, so they are not specific to the scene."""
    return _download_first(pool, assets_dir, index, used_urls, "wikipedia_topic", "wikitopic")


def from_wikipedia(query: str, assets_dir: Path, index: int, used_urls: set[str]) -> dict | None:
    """Images from the Vietnamese Wikipedia articles matching this scene's own keywords."""
    if not query:
        return None
    try:
        candidates = wikipedia_vi_pool(query, articles=2)
    except (OSError, ValueError) as error:
        logger.warning("wikipedia_search_failed query=%s error=%s code=%s",
                       query, type(error).__name__, getattr(error, "code", ""))
        return None
    return _download_first(candidates, assets_dir, index, used_urls, "wikipedia", "wikivi")


def from_ai(prompt: str, assets_dir: Path, index: int) -> dict:
    content = generate_image(_AI_STYLE + prompt)
    target = assets_dir / f"scene_{index:02d}_ai.png"
    if not _save(content, target):
        raise ImageError("Ảnh AI trả về không đọc được.")
    return {"file": target.name, "source": "ai", "url": "", "page": "", "credit": "Ảnh minh họa AI"}


def from_pollinations(prompt: str, assets_dir: Path, index: int) -> dict:
    """Free anonymous text-to-image; spaced out because the anonymous tier is rate limited."""
    global _pollinations_last_call
    url = f"{_POLLINATIONS_URL}{quote(_AI_STYLE + prompt, safe='')}?" + urlencode(
        {"width": 1080, "height": 1920, "nologo": "true"})
    with _pollinations_lock:
        wait = _POLLINATIONS_MIN_INTERVAL - (time.monotonic() - _pollinations_last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            content = _fetch(url, timeout=120)
        except (OSError, ValueError) as error:
            raise ImageError(f"Cảnh {index + 1}: Pollinations không tạo được ảnh ({type(error).__name__}: "
                             f"{getattr(error, 'code', '') or error}).") from error
        finally:
            _pollinations_last_call = time.monotonic()
    target = assets_dir / f"scene_{index:02d}_pollinations.jpg"
    if not _save(content, target):
        raise ImageError(f"Cảnh {index + 1}: ảnh Pollinations trả về không đọc được.")
    return {"file": target.name, "source": "pollinations", "url": "", "page": "",
            "credit": "Minh họa AI (Pollinations)"}


_PLACEHOLDER_COLORS = ("#1e3a8a", "#7f1d1d", "#14532d", "#78350f", "#4c1d95", "#134e4a", "#831843", "#1f2937")
_font_family: str | None = None
_qt_application = None


def _placeholder_font_family() -> str:
    """Load the video font file explicitly; without a platform font database (offscreen) text renders as boxes."""
    global _font_family, _qt_application
    from PySide6.QtGui import QFontDatabase, QGuiApplication

    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _qt_application = QGuiApplication([])
    if _font_family is None:
        font_id = QFontDatabase.addApplicationFont(os.environ.get("KV_VIDEO_FONT") or "C:/Windows/Fonts/arial.ttf")
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        _font_family = families[0] if families else "Arial"
    return _font_family


def placeholder(title: str, text: str, assets_dir: Path, index: int) -> dict:
    """Draw a clearly-labelled 9:16 stand-in so a scene without any found image can still be rendered."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter

    family = _placeholder_font_family()
    width, height = 1080, 1920
    image = QImage(width, height, QImage.Format_RGB32)
    gradient = QLinearGradient(0, 0, 0, height)
    gradient.setColorAt(0, QColor(_PLACEHOLDER_COLORS[index % len(_PLACEHOLDER_COLORS)]))
    gradient.setColorAt(1, QColor("#0b1120"))
    painter = QPainter(image)
    painter.fillRect(0, 0, width, height, gradient)
    painter.setPen(QColor("#e2e8f0"))
    painter.setFont(QFont(family, 34, QFont.Bold))
    painter.drawText(QRect(90, 560, width - 180, 260), Qt.AlignCenter | Qt.TextWordWrap, title)
    painter.setFont(QFont(family, 26))
    painter.drawText(QRect(90, 860, width - 180, 560), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, text)
    painter.setPen(QColor("#94a3b8"))
    painter.setFont(QFont(family, 18))
    painter.drawText(QRect(0, height - 260, width, 80), Qt.AlignCenter, f"Cảnh {index + 1} — ảnh thay thế")
    painter.end()
    target = assets_dir / f"scene_{index:02d}_placeholder.png"
    if not image.save(str(target), "PNG") or not _is_image(target):
        raise ImageError(f"Cảnh {index + 1}: không tạo được ảnh thay thế.")
    return {"file": target.name, "source": "placeholder", "url": "", "page": "", "credit": "Ảnh thay thế (chưa có ảnh phù hợp)"}


def _topic_queries(topic: str, subject: dict | None = None) -> list[str]:
    """Short subject names first (they search far better than a whole topic sentence), then the topic itself."""
    folded = unicodedata.normalize("NFKD", topic.replace("đ", "d").replace("Đ", "D"))
    folded = folded.encode("ascii", "ignore").decode("ascii")
    candidates = ((subject or {}).get("en", ""), (subject or {}).get("vi", ""), topic.strip(), " ".join(folded.split()))
    return [query for query in dict.fromkeys(candidates) if query]


def fetch_scene_image(scene: dict, assets_dir: Path, index: int, used_urls: set[str], topic: str, title: str,
                      wiki_pool: list[dict], use_pollinations: bool, subject: dict | None = None) -> tuple[dict, list[str]]:
    """Scene keywords first, topic-wide sources only as fallback:
    Commons (VI, EN) → Wikipedia VI (scene) → Openverse → Wikipedia topic pool → Commons (subject/topic)
    → Pollinations → placeholder.

    Returns the image plus warnings worth showing to the user. Gemini is manual-only: it needs a billed key.
    """
    query_vi = scene.get("image_query_vi", "")
    query_en = scene.get("image_query_en", "")
    finders = [
        lambda: from_wikimedia(query_vi, assets_dir, index, used_urls) if query_vi else None,
        lambda: from_wikimedia(query_en, assets_dir, index, used_urls) if query_en else None,
        lambda: from_wikipedia(query_vi, assets_dir, index, used_urls),
        lambda: from_openverse(query_en, assets_dir, index, used_urls) if query_en else None,
        lambda: from_wikipedia_pool(wiki_pool, assets_dir, index, used_urls),
        *(lambda topic_query=topic_query: from_wikimedia(topic_query, assets_dir, index, used_urls)
          for topic_query in _topic_queries(topic, subject)),
    ]
    for finder in finders:
        image = finder()
        if image:
            return image, []
    warnings = []
    if use_pollinations:
        try:
            return from_pollinations(scene["image_prompt"], assets_dir, index), []
        except ImageError as error:
            logger.warning("pollinations_failed index=%d", index)
            warnings.append(str(error))
    return placeholder(title, scene["text"], assets_dir, index), warnings
