"""One error shape for every failure: {code, message, request_id}."""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from parchi.api.middleware import current_request_id


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str | None


class AppError(Exception):
    """Raise from routes to return a specific error code and message."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, request_id=current_request_id())
    return JSONResponse(status_code=status_code, content=body.model_dump())


def _code_for(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_")
    except ValueError:
        return "error"


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(exc.status_code, _code_for(exc.status_code), message)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Field names and pydantic's message only: never the submitted values.
    problems = sorted(
        {
            f"{'.'.join(str(part) for part in err['loc'])}: "
            + str(err["msg"]).removeprefix("Value error, ")
            for err in exc.errors()
        }
    )
    return error_response(422, "validation_error", "; ".join(problems))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
