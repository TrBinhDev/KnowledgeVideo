import json
import logging
from abc import ABC, abstractmethod


class AIError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ProviderNotConfigured(AIError):
    pass


class ProviderAuthenticationError(AIError):
    pass


class ProviderTimeout(AIError):
    pass


class ProviderResponseError(AIError):
    pass


class ProviderModelUnavailable(ProviderResponseError):
    """This model cannot serve now (overloaded, quota, retired) but another model of the same provider may."""


def parse_json_text(content: str, provider: str) -> dict:
    """Parse model text into a JSON object, tolerating a surrounding markdown fence."""
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        # The gateway sometimes returns a complete JSON object followed by extra text (often the object again):
        # json.loads fails with "Extra data". Keep the first complete object.
        start = text.find("{")
        try:
            data, end = json.JSONDecoder().raw_decode(text[start:]) if start >= 0 else (None, 0)
        except json.JSONDecodeError:
            data = None
        if data is None:
            raise ProviderResponseError(f"Phản hồi từ {provider} không phải JSON hợp lệ.") from error
        logging.getLogger("kv.ai").warning("json_extra_text_ignored provider=%s kept=%d of %d chars",
                                           provider, end, len(text) - start)
    if not isinstance(data, dict):
        raise ProviderResponseError(f"Phản hồi từ {provider} phải là một đối tượng JSON.")
    return data


class BaseAIProvider(ABC):
    # Optional progress(stage, percent) callback set by the caller; percent -1 means "no percentage".
    notify = None

    def _notify(self, text: str) -> None:
        if self.notify:
            self.notify(text, -1)

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier, e.g. 'ollama' or 'gemini'."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier used for the request."""

    @abstractmethod
    def generate_json(self, system_prompt: str, user_prompt: str, schema: dict, temperature: float = 0.5) -> dict:
        """Return the model answer parsed as a JSON object shaped by `schema` (JSON Schema).

        Raises ProviderNotConfigured, ProviderAuthenticationError, ProviderTimeout or ProviderResponseError.
        """
