import base64
import json
import logging
import os
import re
import ssl
import threading
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Mozilla's certificate bundle: the Windows root store here still holds an expired Let's Encrypt root that breaks
# gateways using Let's Encrypt certificates (shopaikey), as it broke Wikimedia before.
from core.network_security import _TLS_CONTEXT
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
# ListModels still returns models retired for new users (they answer 404); remember them for this session,
# per endpoint (a model missing at Google may exist at a gateway and the other way round).
_retired_models: set[tuple[str, str]] = set()


def _model_rank(name: str) -> tuple:
    """Plain flash first, then flash-lite, then the rest; newest version first; '-latest' aliases lead their group."""
    family = 0 if "flash" in name and "lite" not in name else 1 if "flash" in name else 2
    match = re.match(r"gemini-(\d+(?:\.\d+)?)", name)
    version = 99.0 if name.endswith("-latest") else float(match.group(1)) if match else 0.0
    return family, -version, name

logger = logging.getLogger("kv.ai.gemini")


@dataclass(frozen=True)
class Endpoint:
    """Where Gemini requests go: Google itself, or a third-party gateway serving the same generateContent format.

    Each has its own .env variables, so a gateway key can be used next to a Google key.
    """
    name: str
    label: str
    key_env: str
    base_env: str
    model_env: str
    default_base: str
    # Google takes the key in x-goog-api-key; gateways document "Authorization: Bearer <key>".
    bearer: bool

    def api_key(self) -> str:
        return (os.environ.get(self.key_env) or "").strip()

    def base_url(self) -> str:
        base = (os.environ.get(self.base_env) or self.default_base).strip().rstrip("/")
        if not base:
            raise ProviderNotConfigured(f"Chưa cấu hình {self.base_env} trong file .env (Cài đặt).")
        return base

    def headers(self, api_key: str) -> dict:
        auth = {"Authorization": f"Bearer {api_key}"} if self.bearer else {"x-goog-api-key": api_key}
        return {**auth, "User-Agent": "KnowledgeVideo/0.1"}

    def default_model(self) -> str:
        return os.environ.get(self.model_env) or DEFAULT_MODEL


GOOGLE = Endpoint("gemini", "Gemini", "KV_GEMINI_API_KEY", "KV_GEMINI_BASE_URL", "KV_GEMINI_MODEL",
                  "https://generativelanguage.googleapis.com/v1beta", bearer=False)
GATEWAY = Endpoint("gateway", "Cổng API", "KV_GATEWAY_API_KEY", "KV_GATEWAY_BASE_URL", "KV_GATEWAY_MODEL",
                   "", bearer=True)

# Token use of this session per endpoint, logged after every call so the spent credit can be followed.
_usage: dict[str, list[int]] = {}
_usage_lock = threading.Lock()


def _log_usage(endpoint: Endpoint, model: str, data: dict) -> None:
    meta = data.get("usageMetadata") or {}
    prompt = int(meta.get("promptTokenCount") or 0)
    # Thinking tokens are billed as output.
    output = int(meta.get("candidatesTokenCount") or 0) + int(meta.get("thoughtsTokenCount") or 0)
    with _usage_lock:
        total = _usage.setdefault(endpoint.name, [0, 0])
        total[0] += prompt
        total[1] += output
        session_in, session_out = total
    logger.info("gemini_tokens %s model=%s in=%d out=%d | phiên này: in=%d out=%d",
                endpoint.label, model, prompt, output, session_in, session_out)


def _api_key() -> str:
    return GOOGLE.api_key()


def _timeout(default: float) -> float:
    try:
        return float(os.environ.get("KV_GEMINI_TIMEOUT_SECONDS") or default)
    except (TypeError, ValueError):
        return default


def _reason(error: Exception) -> str:
    return str(getattr(error, "reason", None) or error)[:160]


def _is_certificate_error(error: Exception) -> bool:
    return isinstance(getattr(error, "reason", None), ssl.SSLError) or isinstance(error, ssl.SSLError)


def _google_message(error: HTTPError) -> str:
    try:
        return str((json.loads(error.read().decode("utf-8")).get("error") or {}).get("message", ""))[:160]
    except (OSError, ValueError, AttributeError):
        return ""


def list_models(endpoint: Endpoint = GOOGLE) -> list[str]:
    """Text models this API key can call with generateContent, fastest families first."""
    api_key = endpoint.api_key()
    if not api_key:
        raise ProviderNotConfigured(f"Chưa cấu hình {endpoint.key_env} trong file .env (Cài đặt).")
    request = Request(f"{endpoint.base_url()}/models?pageSize=200", headers=endpoint.headers(api_key))
    try:
        with urlopen(request, timeout=_timeout(30.0), context=_TLS_CONTEXT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code in (401, 403):
            raise ProviderAuthenticationError(
                f"Xác thực {endpoint.label} thất bại. Kiểm tra lại {endpoint.key_env}.") from error
        if error.code == 404:
            raise ProviderResponseError(
                f"{endpoint.label} không có danh sách model ở {endpoint.base_url()}/models (HTTP 404). Kiểm tra "
                f"{endpoint.base_env}: cần địa chỉ định dạng Gemini, thường kết thúc bằng /v1beta.") from error
        raise ProviderResponseError(f"Không lấy được danh sách model {endpoint.label} (HTTP {error.code}).") from error
    except (TimeoutError, URLError, OSError, ValueError) as error:
        if _is_certificate_error(error):
            raise ProviderResponseError(f"Lỗi chứng chỉ SSL khi kết nối {endpoint.label}: {_reason(error)}") from error
        raise ProviderResponseError(
            f"Không lấy được danh sách model {endpoint.label}. Kiểm tra mạng ({_reason(error)}).") from error
    # Gateways (shopaikey) list every model with "supportedGenerationMethods": null; unknown is kept and the
    # name filter below removes the non-text models.
    names = [
        str(item.get("name", "")).removeprefix("models/") for item in data.get("models") or []
        if isinstance(item, dict) and (item.get("supportedGenerationMethods") is None
                                       or "generateContent" in item["supportedGenerationMethods"])
    ]
    names = [name for name in names if name.startswith("gemini-") and (endpoint.name, name) not in _retired_models
             and not any(mark in name for mark in _NON_TEXT_MARKERS)]
    return sorted(names, key=_model_rank)


def _post(endpoint: Endpoint, model: str, payload: dict, api_key: str, timeout: float) -> dict:
    request = Request(
        f"{endpoint.base_url()}/models/{model}:generateContent",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **endpoint.headers(api_key)},
        method="POST",
    )
    label = endpoint.label
    try:
        with urlopen(request, timeout=timeout, context=_TLS_CONTEXT) as response:
            raw_response = response.read()
    except HTTPError as error:
        if error.code in (401, 403):
            raise ProviderAuthenticationError(f"Xác thực {label} thất bại. Kiểm tra lại {endpoint.key_env}.") from error
        if error.code == 404:
            _retired_models.add((endpoint.name, model))
            raise ProviderModelUnavailable(
                f"Model '{model}' ({label}) không dùng được: {_google_message(error) or 'không tìm thấy'}") from error
        if error.code == 429:
            raise ProviderModelUnavailable(f"Model '{model}' ({label}) hết lượt gọi, hết quota hoặc hết credit.") from error
        if error.code == 503:
            raise ProviderModelUnavailable(f"Model '{model}' ({label}) đang quá tải.") from error
        raise ProviderResponseError(f"{label} trả về lỗi HTTP {error.code}. {_google_message(error)}".strip()) from error
    except (TimeoutError, URLError, OSError) as error:
        message = str(error).lower()
        if isinstance(error, TimeoutError) or "timed out" in message or "timeout" in message:
            raise ProviderTimeout(f"Quá thời gian chờ phản hồi từ {label} (>{timeout:.0f}s).") from error
        if _is_certificate_error(error):
            raise ProviderResponseError(f"Lỗi chứng chỉ SSL khi kết nối {label}: {_reason(error)}") from error
        raise ProviderResponseError(
            f"Không thể kết nối tới {label}. Kiểm tra mạng và {endpoint.base_env} ({_reason(error)}).") from error
    try:
        data = json.loads(raw_response.decode("utf-8"))
    except (TypeError, ValueError) as error:
        raise ProviderResponseError(f"Phản hồi từ {label} không đúng định dạng Gemini.") from error
    if not isinstance(data, dict):
        raise ProviderResponseError(f"Phản hồi từ {label} không đúng định dạng Gemini.")
    _log_usage(endpoint, model, data)
    return data


def _parts(data: dict) -> list[dict]:
    candidates = data.get("candidates") or []
    parts = (candidates[0].get("content") or {}).get("parts") if candidates else None
    if not parts:
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        raise ProviderResponseError(f"Gemini không trả về nội dung{f' ({reason})' if reason else ''}.")
    return [part for part in parts if isinstance(part, dict)]


class GeminiProvider(BaseAIProvider):
    """Gemini text provider using the generateContent REST API (at Google or at a gateway)."""

    def __init__(self, api_key: str | None = None, model: str | None = None, fallback_models: list[str] | None = None,
                 endpoint: Endpoint = GOOGLE):
        self._endpoint = endpoint
        self._api_key = api_key if api_key is not None else endpoint.api_key()
        self._model = model or endpoint.default_model()
        self._fallbacks = [name for name in fallback_models or []
                           if name and name != self._model and (endpoint.name, name) not in _retired_models]
        self._timeout = _timeout(90.0)

    @property
    def provider_name(self) -> str:
        return self._endpoint.name

    @property
    def model_name(self) -> str:
        return self._model

    def generate_json(self, system_prompt: str, user_prompt: str, schema: dict, temperature: float = 0.5) -> dict:
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature, "maxOutputTokens": 8192},
        }
        return self._generate(payload, len(user_prompt))

    def generate_json_images(self, prompt: str, image_paths: list, schema: dict, temperature: float = 0.0) -> dict:
        """Look at JPEG images and answer JSON shaped like `schema` (the vision steps of the clip flow)."""
        parts = [{"text": f"{prompt}\nJSON schema of the answer: {json.dumps(schema)}"}]
        parts += [{"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(path.read_bytes()).decode("ascii")}}
                  for path in image_paths]
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature, "maxOutputTokens": 4096},
        }
        return self._generate(payload, len(prompt), images=len(image_paths))

    def _generate(self, payload: dict, prompt_length: int, images: int = 0) -> dict:
        endpoint = self._endpoint
        if not self._api_key:
            raise ProviderNotConfigured(f"Chưa cấu hình {endpoint.key_env} trong file .env (Cài đặt).")
        models = [self._model, *self._fallbacks]
        failures = []
        for position, model in enumerate(models):
            self._notify(f"{endpoint.label}: {model}")
            logger.info("gemini_request %s model=%s prompt_len=%d images=%d", endpoint.label, model, prompt_length, images)
            try:
                data = _post(endpoint, model, payload, self._api_key, self._timeout)
            except ProviderModelUnavailable as error:
                logger.warning("gemini_model_unavailable model=%s reason=%s", model, error.message)
                failures.append(error.message)
                if position + 1 < len(models):
                    self._notify(f"{model} không dùng được, chuyển sang {models[position + 1]}")
                continue
            self._model = model  # model_name now reports the model that actually answered
            self._notify(f"{endpoint.label} đã trả lời: {model}")
            content = "".join(str(part.get("text", "")) for part in _parts(data)).strip()
            try:
                return parse_json_text(content, endpoint.label)
            except ProviderResponseError as error:
                # Broken JSON (cut off or mangled) is usually a one-off: ask the same model once more.
                logger.warning("gemini_invalid_json model=%s chars=%d retrying", model, len(content))
                self._notify(f"{endpoint.label} trả JSON lỗi, gọi lại {model}")
                retry = _post(endpoint, model, payload, self._api_key, self._timeout)
                content = "".join(str(part.get("text", "")) for part in _parts(retry)).strip()
                try:
                    return parse_json_text(content, endpoint.label)
                except ProviderResponseError:
                    raise error from None
        hint = "" if self._fallbacks else " Bấm \"Làm mới\" danh sách model để có model dự phòng."
        raise ProviderModelUnavailable(f"Không model nào của {endpoint.label} dùng được lúc này:\n- "
                                       + "\n- ".join(failures) + hint)


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
    data = _post(GOOGLE, model, payload, api_key, _timeout(120.0))
    for part in _parts(data):
        inline = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline, dict) and inline.get("data"):
            try:
                return base64.b64decode(inline["data"])
            except (TypeError, ValueError) as error:
                raise ProviderResponseError("Ảnh Gemini trả về bị lỗi mã hóa.") from error
    raise ProviderResponseError("Gemini không trả về ảnh cho mô tả này.")
