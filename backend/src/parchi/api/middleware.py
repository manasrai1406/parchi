"""Request ids, request logging, and the last-resort 500 handler."""

import re
import time
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from parchi.logging import bind_context, clear_context, get_logger

REQUEST_ID_HEADER = "x-request-id"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

log = get_logger(__name__)


def current_request_id() -> str | None:
    return _request_id.get()


def _incoming_request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == REQUEST_ID_HEADER.encode():
            candidate = value.decode("latin-1")
            if _SAFE_REQUEST_ID.match(candidate):
                return candidate
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Binds a request id to every log line and returns it in X-Request-ID.

    Unhandled errors are caught here, while the request id is still bound, and turned
    into the standard error shape.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope)
        token = _request_id.set(request_id)
        clear_context()
        bind_context(request_id=request_id)

        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            log.exception("request.unhandled_error")
            if response_started:
                raise
            # Imported here to avoid a cycle: errors.py reads the request id from this module.
            from parchi.api.errors import error_response

            response = error_response(500, "internal_error", "Something went wrong.")
            await response(scope, receive, send_with_request_id)
        finally:
            # The path only: query strings may carry search terms.
            log.info(
                "request.finished",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            clear_context()
            _request_id.reset(token)
