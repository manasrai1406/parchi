"""structlog setup.

Readable output in development, JSON in production, and always JSON in the rotating
log file. Ids are bound through context variables so every line carries them.

Never log receipt text, extracted values, file contents or API keys: log ids and
field names only. `redact_sensitive` is a safety net for mistakes, not a licence.
"""

import logging
import logging.handlers
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

from parchi.config import Settings

# The only keys that may be bound to the logging context.
# user_id: who made the request (D-043); never a username, password or token.
CONTEXT_KEYS = frozenset({"request_id", "user_id", "batch_id", "file_id", "run_id", "ref_no"})

# Keys whose values are never written, whatever the caller passes.
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "content",
        "password",
        "raw",
        "secret",
        "text",
        "token",
        "value",
        "values",
    }
)
REDACTED = "[redacted]"


def redact_sensitive(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    for key in event_dict:
        lowered = key.lower()
        if lowered in SENSITIVE_KEYS or lowered.endswith(("_key", "_secret", "_token", "_text")):
            event_dict[key] = REDACTED
    return event_dict


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
        structlog.processors.StackInfoRenderer(),
    ]


def _formatter(renderer: Any) -> structlog.stdlib.ProcessorFormatter:
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )


def configure_logging(settings: Settings) -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *_shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console = logging.StreamHandler()
    console.setFormatter(
        _formatter(
            structlog.processors.JSONRenderer()
            if settings.json_logs
            else structlog.dev.ConsoleRenderer(colors=False)
        )
    )
    handlers: list[logging.Handler] = [console]

    if settings.log_dir is not None:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            settings.log_dir / "parchi.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(_formatter(structlog.processors.JSONRenderer()))
        handlers.append(file_handler)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # Route uvicorn through our handlers. Requests are logged by our middleware.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False


def bind_context(**ids: object) -> None:
    """Bind ids (request_id, user_id, batch_id, file_id, run_id, ref_no) to later log lines."""
    unknown = set(ids) - CONTEXT_KEYS
    if unknown:
        raise ValueError(f"Not a logging context key: {', '.join(sorted(unknown))}")
    structlog.contextvars.bind_contextvars(**ids)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)


__all__ = [
    "CONTEXT_KEYS",
    "bind_context",
    "clear_context",
    "configure_logging",
    "get_logger",
    "redact_sensitive",
]
