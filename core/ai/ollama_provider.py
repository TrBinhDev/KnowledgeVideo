import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.ai.base import (
    BaseAIProvider,
    ProviderAuthenticationError,
    ProviderNotConfigured,
    ProviderResponseError,
    ProviderTimeout,
    parse_json_text,
)

logger = logging.getLogger("kv.ai.ollama")

DEFAULT_MODEL = "gemma3"
# Rough size (characters) beyond which the prompt needs a larger context window than the default.
LONG_PROMPT_CHARS = 5000
LONG_PROMPT_CONTEXT = 16384


def _server_url() -> str:
    return (os.environ.get("KV_OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/").removesuffix("/api/chat")


def list_models() -> list[str]:
    """Models already pulled into the local Ollama server."""
    try:
        with urlopen(Request(f"{_server_url()}/api/tags", headers={"User-Agent": "KnowledgeVideo/0.1"}), timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (TimeoutError, URLError, OSError, ValueError) as error:
        raise ProviderNotConfigured(
            "Không kết nối được Ollama tại localhost:11434. Hãy mở Ollama rồi bấm Làm mới.") from error
    return [str(item.get("name")) for item in data.get("models") or [] if item.get("name")]


class OllamaProvider(BaseAIProvider):
    """Local AI provider backed by the Ollama HTTP API."""

    def __init__(self, base_url: str | None = None, model: str | None = None, timeout: float | None = None):
        configured_url = (base_url or _server_url()).rstrip("/")
        self._url = configured_url if configured_url.endswith("/api/chat") else f"{configured_url}/api/chat"
        self._model = model or os.environ.get("KV_OLLAMA_MODEL") or DEFAULT_MODEL
        try:
            self._timeout = float(timeout or os.environ.get("KV_OLLAMA_TIMEOUT_SECONDS", "240.0"))
        except (TypeError, ValueError):
            self._timeout = 240.0

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    def generate_json(self, system_prompt: str, user_prompt: str, schema: dict, temperature: float = 0.5) -> dict:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # Small local models often return "{}" with plain "json" mode; a schema constrains decoding.
            "format": schema,
            "stream": False,
            "options": {"temperature": temperature},
        }
        # Ollama's default context window is small and silently drops the start of long prompts (source documents).
        if len(system_prompt) + len(user_prompt) > LONG_PROMPT_CHARS:
            payload["options"]["num_ctx"] = LONG_PROMPT_CONTEXT
        request = Request(
            self._url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "KnowledgeVideo/0.1"},
            method="POST",
        )
        self._notify(f"Ollama: {self._model}")
        logger.info("ollama_request model=%s prompt_len=%d", self._model, len(user_prompt))
        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw_response = response.read()
        except HTTPError as error:
            if error.code in (401, 403):
                raise ProviderAuthenticationError("Ollama yêu cầu xác thực; hãy dùng local API tại localhost:11434.") from error
            if error.code == 404:
                raise ProviderNotConfigured(f"Chưa tải model Ollama '{self._model}'. Hãy chạy: ollama pull {self._model}") from error
            raise ProviderResponseError(f"Ollama trả về lỗi HTTP {error.code}.") from error
        except (TimeoutError, URLError, OSError) as error:
            message = str(error).lower()
            if isinstance(error, TimeoutError) or "timed out" in message or "timeout" in message:
                raise ProviderTimeout(f"Ollama xử lý quá thời gian chờ (>{self._timeout:.0f}s).") from error
            raise ProviderNotConfigured(
                "Không kết nối được Ollama tại localhost:11434. Hãy mở Ollama và kiểm tra model đã được tải."
            ) from error

        try:
            response_data = json.loads(raw_response.decode("utf-8"))
            content = (response_data.get("message") or {}).get("content") or response_data.get("response") or ""
        except (AttributeError, TypeError, ValueError) as error:
            raise ProviderResponseError("Phản hồi từ Ollama không đúng định dạng.") from error
        return parse_json_text(str(content), "Ollama")
