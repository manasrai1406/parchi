import pytest
from pydantic import ValidationError

from parchi.config import AppEnv, Settings


def make(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_ai_is_off_by_default() -> None:
    settings = make()
    assert settings.ai_enabled is False
    assert settings.ai_daily_cap == 50


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@db:5432/parchi",
        "postgres://u:p@db:5432/parchi",
        "postgresql+psycopg://u:p@db:5432/parchi",
    ],
)
def test_database_url_uses_psycopg(url: str) -> None:
    assert make(database_url=url).database_url == "postgresql+psycopg://u:p@db:5432/parchi"


def test_non_postgres_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make(database_url="sqlite:///parchi.db")


def test_empty_api_keys_and_log_dir_become_none() -> None:
    settings = make(anthropic_api_key="", openai_api_key="", log_dir="")
    assert settings.anthropic_api_key is None
    assert settings.openai_api_key is None
    assert settings.log_dir is None


def test_api_keys_are_hidden_in_repr() -> None:
    settings = make(anthropic_api_key="sk-secret-value")
    assert "sk-secret-value" not in repr(settings)


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make(app_timezone="Mars/Olympus")


def test_log_level_is_checked() -> None:
    assert make(log_level="DEBUG").log_level == "debug"
    with pytest.raises(ValidationError):
        make(log_level="loud")


def test_session_cookie_defaults() -> None:
    settings = make()
    assert (settings.cookie_secure, settings.session_days) == (False, 7)
    with pytest.raises(ValidationError):
        make(session_days=0)


def test_json_logs_only_in_production() -> None:
    assert make(app_env=AppEnv.PRODUCTION).json_logs is True
    assert make(app_env=AppEnv.DEVELOPMENT).json_logs is False
