"""Settings read from the environment (and a local .env file)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


def to_async_url(url: str) -> str:
    """Point a plain postgresql:// URL at the psycopg 3 driver."""
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    raise ValueError("DATABASE_URL must be a PostgreSQL URL")


class Settings(BaseSettings):
    # The repo-root .env is read when running from backend/; a local .env overrides it.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_env: AppEnv = AppEnv.DEVELOPMENT
    app_timezone: str = "Asia/Kolkata"

    database_url: str = "postgresql://postgres:postgres@localhost:5432/parchi"
    redis_url: str = "redis://localhost:6379"
    storage_dir: Path = Path("data/uploads")

    # Upload limits (D-016).
    max_upload_mb: int = Field(default=20, ge=1, le=500)
    max_files_per_batch: int = Field(default=50, ge=1, le=1000)

    log_level: str = "info"
    log_dir: Path | None = Path("logs")

    # Login sessions (D-043). Set COOKIE_SECURE=true when Parchi is served over HTTPS, so
    # the browser only sends the session cookie over encrypted connections.
    cookie_secure: bool = False
    session_days: int = Field(default=7, ge=1, le=90)
    # Anyone can create a Viewer account from the login page (D-046). Turn it off when
    # Parchi can be reached by people who should not see the receipts.
    allow_signup: bool = True

    # Where receipts kept as tests are copied, with their confirmed answers (D-048). Unset
    # means the Review page cannot keep them. Under data/, so never committed.
    real_samples_dir: Path | None = None

    # AI is off unless explicitly enabled, and even then every call needs approval.
    ai_enabled: bool = False
    ai_daily_cap: int = Field(default=50, ge=0)
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    # Models used when a person approves AI (D-035).
    anthropic_model: str = "claude-sonnet-5"
    openai_model: str = "gpt-6-sol"
    gemini_model: str = "gemini-3.6-flash"
    ai_timeout_seconds: float = Field(default=120.0, gt=0, le=600)

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        return to_async_url(value)

    @field_validator("log_level")
    @classmethod
    def _check_log_level(cls, value: str) -> str:
        value = value.lower()
        if value not in {"debug", "info", "warning", "error", "critical"}:
            raise ValueError("LOG_LEVEL must be debug, info, warning, error or critical")
        return value

    @field_validator("app_timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown APP_TIMEZONE: {value}") from exc
        return value

    @field_validator(
        "log_dir", "anthropic_api_key", "openai_api_key", "gemini_api_key", mode="before"
    )
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def json_logs(self) -> bool:
        return self.app_env == AppEnv.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
