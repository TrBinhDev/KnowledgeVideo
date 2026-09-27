import base64
import json
import logging
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.ai.base import (
    BaseAIProvider,
    ProviderAuthenticationError,
    ProviderModelUnavailable,
    ProviderNotConfigured,
    ProviderResponseError,
    ProviderTimeout,
    parse_json_text,
)

DEFAULT_MODEL = "gemini-3.8-flash"
# Models that list generateContent but are not plain text/JSON chat models.
_NON_TEXT_MARKERS = ("image", "tts", "audio", "live", "embedding", "customtools", "computer", "robotics", "transcribe")
# ListModels still returns models retired for new users (they answer 404); remember them for this session.
_retired_models: set[str] = set()


def _model_rank(name: str) -> tuple:
    """Plain flash first, then flash-lite, then the rest; newest version first; '-latest' aliases lead their group."""
    family = 0 if "flash" in name and "lite" not in name else 1 if "flash" in name else 2
    match = re.match(r"gemini-(\d+(?:\.\d+)?)", name)
    version = 99.0 if name.endswith("-latest") else float(match.group(1)) if match else 0.0
    return family, -version, name

logger = logging.getLogger("kv.ai.gemini")


def _api_key() -> str:
    return (os.environ.get("KV_GEMINI_API_KEY") or "").strip()


def _base_url() -> str:
    return (os.environ.get("KV_GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")


def _timeout(default: float) -> float:
    try:
        return float(os.environ.get("KV_GEMINI_TIMEOUT_SECONDS") or default)
    except (TypeError, ValueError):
        return default


def _google_message(error: HTTPError) -> str:
    try:
        return str((json.loads(error.read().decode("utf-8")).get("error") or {}).get("message", ""))[:160]
    except (OSError, ValueError, AttributeError):
        return ""


def list_models() -> list[str]:
    """Text models this API key can call with generateContent, fastest families first."""
    api_key = _api_key()
    if not api_key:
        raise ProviderNotConfigured("Chưa cấu hình KV_GEMINI_API_KEY trong file .env.")
    request = Request(f"{_base_url()}/models?pageSize=200",
                      headers={"x-goog-api-key": api_key, "User-Agent": "KnowledgeVideo/0.1"})
    try:
        with urlopen(request, timeout=_timeout(30.0)) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code in (401, 403):
            raise ProviderAuthenticationError("Xác thực Gemini thất bại. Kiểm tra lại KV_GEMINI_API_KEY.") from error
        raise ProviderResponseError(f"Không lấy được danh sách model Gemini (HTTP {error.code}).") from error
    except (TimeoutError, URLError, OSError, ValueError) as error:
        raise ProviderResponseError("Không lấy được danh sách model Gemini. Kiểm tra mạng.") from error
    names = [
        str(item.get("name", "")).removeprefix("models/") for item in data.get("models") or []
        if "generateContent" in (item.get("supportedGenerationMethods") or [])
    ]
    names = [name for name in names if name.startswith("gemini-") and name not in _retired_models
             and not any(mark in name for mark in _NON_TEXT_MARKERS)]
    return sorted(names, key=_model_rank)


def _post(url: str, payload: dict, api_key: str, timeout: float, model: str) -> dict:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key, "User-Agent": "KnowledgeVideo/0.1"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw_response = response.read()
    except HTTPError as error:
        if error.code in (401, 403):
            raise ProviderAuthenticationError("Xác thực Gemini thất bại. Kiểm tra lại KV_GEMINI_API_KEY.") from error
        if error.code == 404:
            _retired_models.add(model)
            raise ProviderModelUnavailable(
                f"Model Gemini '{model}' không dùng được: {_google_message(error) or 'không tìm thấy'}") from error
        if error.code == 429:
            raise ProviderModelUnavailable(f"Model Gemini '{model}' hết lượt gọi hoặc hết quota.") from error
        if error.code == 503:
            raise ProviderModelUnavailable(f"Model Gemini '{model}' đang quá tải phía Google.") from error
        raise ProviderResponseError(f"Gemini trả về lỗi HTTP {error.code}.") from error
    except (TimeoutError, URLError, OSError) as error:
        message = str(error).lower()
        if isinstance(error, TimeoutError) or "timed out" in message or "timeout" in message:
            raise ProviderTimeout(f"Quá thời gian chờ phản hồi từ Gemini (>{timeout:.0f}s).") from error
        raise ProviderResponseError("Không thể kết nối tới Gemini. Kiểm tra mạng và API Key.") from error
    try:
        data = json.loads(raw_response.decode("utf-8"))
    except (TypeError, ValueError) as error:
        raise ProviderResponseError("Phản hồi từ Gemini không đúng định dạng.") from error
    if not isinstance(data, dict):
        raise ProviderResponseError("Phản hồi từ Gemini không đúng định dạng.")
    return data


def _parts(data: dict) -> list[dict]:
    candidates = data.get("candidates") or []
    parts = (candidates[0].get("content") or {}).get("parts") if candidates else None
    if not parts:
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        raise ProviderResponseError(f"Gemini không trả về nội dung{f' ({reason})' if reason else ''}.")
    return [part for part in parts if isinstance(part, dict)]


class GeminiProvider(BaseAIProvider):
    """Gemini text provider using the generateContent REST API."""

    def __init__(self, api_key: str | None = None, model: str | None = None, fallback_models: list[str] | None = None):
        self._api_key = api_key if api_key is not None else _api_key()
        self._model = model or os.environ.get("KV_GEMINI_MODEL") or DEFAULT_MODEL
        self._fallbacks = [name for name in fallback_models or []
                           if name and name != self._model and name not in _retired_models]
        self._timeout = _timeout(90.0)

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def generate_json(self, system_prompt: str, user_prompt: str, schema: dict, temperature: float = 0.5) -> dict:
        if not self._api_key:
            raise ProviderNotConfigured("Chưa cấu hình KV_GEMINI_API_KEY trong file .env.")
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature, "maxOutputTokens": 8192},
        }
        models = [self._model, *self._fallbacks]
        failures = []
        for position, model in enumerate(models):
            self._notify(f"Gemini: {model}")
            logger.info("gemini_request model=%s prompt_len=%d", model, len(user_prompt))
            try:
                data = _post(f"{_base_url()}/models/{model}:generateContent", payload, self._api_key, self._timeout, model)
            except ProviderModelUnavailable as error:
                logger.warning("gemini_model_unavailable model=%s reason=%s", model, error.message)
                failures.append(error.message)
                if position + 1 < len(models):
                    self._notify(f"{model} không dùng được, chuyển sang {models[position + 1]}")
                continue
            self._model = model  # model_name now reports the model that actually answered
            self._notify(f"Gemini đã trả lời: {model}")
            content = "".join(str(part.get("text", "")) for part in _parts(data)).strip()
            return parse_json_text(content, "Gemini")
        hint = "" if self._fallbacks else " Bấm \"Làm mới\" danh sách model để có model dự phòng."
        raise ProviderModelUnavailable("Không model Gemini nào dùng được lúc này:\n- " + "\n- ".join(failures) + hint)


def generate_image(prompt: str, aspect_ratio: str = "9:16") -> bytes:
    """Generate one image with a Gemini image model and return the raw image bytes."""
    api_key = _api_key()
    if not api_key:
        raise ProviderNotConfigured("Chưa cấu hình KV_GEMINI_API_KEY nên không thể tạo ảnh bằng AI.")
    model = os.environ.get("KV_GEMINI_IMAGE_MODEL") or "gemini-2.5-flash-image"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect_ratio}},
    }
    logger.info("gemini_image_request model=%s prompt_len=%d", model, len(prompt))
    data = _post(f"{_base_url()}/models/{model}:generateContent", payload, api_key, _timeout(120.0), model)
    for part in _parts(data):
        inline = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline, dict) and inline.get("data"):
            try:
                return base64.b64decode(inline["data"])
            except (TypeError, ValueError) as error:
                raise ProviderResponseError("Ảnh Gemini trả về bị lỗi mã hóa.") from error
    raise ProviderResponseError("Gemini không trả về ảnh cho mô tả này.")
