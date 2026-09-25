"""FastAPI application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from parchi.api.errors import register_error_handlers
from parchi.api.middleware import RequestContextMiddleware
from parchi.api.routes import batches, files, health
from parchi.config import get_settings
from parchi.db.session import get_engine
from parchi.logging import configure_logging, get_logger
from parchi.pipeline.queue import close_pool

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info("api.started", env=settings.app_env.value, ai_enabled=settings.ai_enabled)
    yield
    await close_pool()
    await get_engine().dispose()
    log.info("api.stopped")


def create_app() -> FastAPI:
    configure_logging(get_settings())
    app = FastAPI(title="Parchi", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(batches.router)
    app.include_router(files.router)
    return app


app = create_app()
