import os

from core import config  # noqa: F401  loads .env so providers see KV_* settings regardless of import order
from core.ai import gemini_provider, ollama_provider
from core.ai.base import (
    AIError,
    BaseAIProvider,
    ProviderAuthenticationError,
    ProviderModelUnavailable,
    ProviderNotConfigured,
    ProviderResponseError,
    ProviderTimeout,
)
from core.ai.gemini_provider import GATEWAY, GOOGLE, GeminiProvider, generate_image
from core.ai.ollama_provider import OllamaProvider

# "gateway" is Gemini through a third-party API gateway (own key, address and model in KV_GATEWAY_*).
PROVIDERS = {"ollama": OllamaProvider, "gemini": GeminiProvider, "gateway": GeminiProvider}
_GEMINI_ENDPOINTS = {"gemini": GOOGLE, "gateway": GATEWAY}
_LISTERS = {"ollama": ollama_provider.list_models,
            "gemini": lambda: gemini_provider.list_models(GOOGLE),
            "gateway": lambda: gemini_provider.list_models(GATEWAY)}


def default_model(name: str) -> str:
    if name in _GEMINI_ENDPOINTS:
        return _GEMINI_ENDPOINTS[name].default_model()
    return os.environ.get("KV_OLLAMA_MODEL") or ollama_provider.DEFAULT_MODEL


def list_models(name: str) -> list[str]:
    try:
        return _LISTERS[name]()
    except KeyError as error:
        raise ProviderNotConfigured(f"AI provider không hỗ trợ: {name}") from error


def build_provider(name: str, model: str | None = None, fallback_models: list[str] | None = None) -> BaseAIProvider:
    """Only Gemini uses fallback models: a local Ollama server is never "overloaded" by Google."""
    if name in _GEMINI_ENDPOINTS:
        return GeminiProvider(model=model, fallback_models=fallback_models, endpoint=_GEMINI_ENDPOINTS[name])
    if name == "ollama":
        return OllamaProvider(model=model)
    raise ProviderNotConfigured(f"AI provider không hỗ trợ: {name}")


__all__ = [
    "AIError",
    "BaseAIProvider",
    "GeminiProvider",
    "OllamaProvider",
    "PROVIDERS",
    "ProviderAuthenticationError",
    "ProviderModelUnavailable",
    "ProviderNotConfigured",
    "ProviderResponseError",
    "ProviderTimeout",
    "build_provider",
    "default_model",
    "generate_image",
    "list_models",
]
