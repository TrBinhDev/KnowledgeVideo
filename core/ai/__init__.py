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
from core.ai.gemini_provider import GeminiProvider, generate_image
from core.ai.ollama_provider import OllamaProvider

PROVIDERS = {"ollama": OllamaProvider, "gemini": GeminiProvider}
_LISTERS = {"ollama": ollama_provider.list_models, "gemini": gemini_provider.list_models}


def default_model(name: str) -> str:
    if name == "gemini":
        return os.environ.get("KV_GEMINI_MODEL") or gemini_provider.DEFAULT_MODEL
    return os.environ.get("KV_OLLAMA_MODEL") or ollama_provider.DEFAULT_MODEL


def list_models(name: str) -> list[str]:
    try:
        return _LISTERS[name]()
    except KeyError as error:
        raise ProviderNotConfigured(f"AI provider không hỗ trợ: {name}") from error


def build_provider(name: str, model: str | None = None, fallback_models: list[str] | None = None) -> BaseAIProvider:
    """Only Gemini uses fallback models: a local Ollama server is never "overloaded" by Google."""
    if name == "gemini":
        return GeminiProvider(model=model, fallback_models=fallback_models)
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
