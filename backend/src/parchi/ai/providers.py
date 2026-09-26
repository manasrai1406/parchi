"""Which AI providers can be used here: those with an API key (D-035)."""

from functools import lru_cache

from parchi.ai.base import Provider
from parchi.config import Settings, get_settings
from parchi.db.enums import AiProvider

LABELS = {AiProvider.ANTHROPIC: "Claude", AiProvider.OPENAI: "OpenAI"}


def model_for(provider: AiProvider, settings: Settings) -> str:
    return settings.anthropic_model if provider == AiProvider.ANTHROPIC else settings.openai_model


def is_configured(provider: AiProvider, settings: Settings) -> bool:
    key = (
        settings.anthropic_api_key if provider == AiProvider.ANTHROPIC else settings.openai_api_key
    )
    return key is not None and bool(key.get_secret_value().strip())


class ProviderNotConfiguredError(RuntimeError):
    pass


@lru_cache(maxsize=2)
def _build(provider: AiProvider) -> Provider:
    settings = get_settings()
    if not is_configured(provider, settings):
        raise ProviderNotConfiguredError(f"{LABELS[provider]} has no API key configured.")
    timeout = settings.ai_timeout_seconds
    if provider == AiProvider.ANTHROPIC:
        from parchi.ai.claude import ClaudeProvider

        key = settings.anthropic_api_key.get_secret_value()  # type: ignore[union-attr]
        return ClaudeProvider(key, settings.anthropic_model, timeout)
    from parchi.ai.openai_provider import OpenAiProvider

    key = settings.openai_api_key.get_secret_value()  # type: ignore[union-attr]
    return OpenAiProvider(key, settings.openai_model, timeout)


def get_provider(provider: AiProvider) -> Provider:
    """The client for a configured provider. Tests replace this function."""
    return _build(provider)
