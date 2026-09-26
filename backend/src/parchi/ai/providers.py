"""Which AI providers can be used here: those with an API key (D-035, D-041)."""

from functools import lru_cache

from pydantic import SecretStr

from parchi.ai.base import Provider
from parchi.config import Settings, get_settings
from parchi.db.enums import AiProvider

LABELS = {
    AiProvider.ANTHROPIC: "Claude",
    AiProvider.OPENAI: "OpenAI",
    AiProvider.GEMINI: "Gemini",
}


def model_for(provider: AiProvider, settings: Settings) -> str:
    return {
        AiProvider.ANTHROPIC: settings.anthropic_model,
        AiProvider.OPENAI: settings.openai_model,
        AiProvider.GEMINI: settings.gemini_model,
    }[provider]


def _key(provider: AiProvider, settings: Settings) -> SecretStr | None:
    return {
        AiProvider.ANTHROPIC: settings.anthropic_api_key,
        AiProvider.OPENAI: settings.openai_api_key,
        AiProvider.GEMINI: settings.gemini_api_key,
    }[provider]


def is_configured(provider: AiProvider, settings: Settings) -> bool:
    key = _key(provider, settings)
    return key is not None and bool(key.get_secret_value().strip())


class ProviderNotConfiguredError(RuntimeError):
    pass


@lru_cache(maxsize=len(AiProvider))
def _build(provider: AiProvider) -> Provider:
    settings = get_settings()
    if not is_configured(provider, settings):
        raise ProviderNotConfiguredError(f"{LABELS[provider]} has no API key configured.")
    key = _key(provider, settings).get_secret_value()  # type: ignore[union-attr]
    model, timeout = model_for(provider, settings), settings.ai_timeout_seconds
    # Each SDK is imported only when its provider is used.
    if provider == AiProvider.ANTHROPIC:
        from parchi.ai.claude import ClaudeProvider

        return ClaudeProvider(key, model, timeout)
    if provider == AiProvider.OPENAI:
        from parchi.ai.openai_provider import OpenAiProvider

        return OpenAiProvider(key, model, timeout)
    from parchi.ai.gemini import GeminiProvider

    return GeminiProvider(key, model, timeout)


def get_provider(provider: AiProvider) -> Provider:
    """The client for a configured provider. Tests replace this function."""
    return _build(provider)
