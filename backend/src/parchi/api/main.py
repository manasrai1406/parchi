"""FastAPI application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from parchi.api.errors import register_error_handlers
from parchi.api.middleware import RequestContextMiddleware
from parchi.api.routes import (
    ai,
    auth,
    batches,
    categories,
    files,
    flags,
    health,
    query,
    receipts,
    users,
)
from parchi.auth.deps import require_viewer
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
    # Open: health checks. Login and user management carry their own checks.
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    # Everything else needs a logged-in user; routes that change data ask for more (D-044).
    logged_in = [Depends(require_viewer)]
    app.include_router(batches.router, dependencies=logged_in)
    # Before files: /files/ai-extract must not be read as a file key.
    app.include_router(ai.router, dependencies=logged_in)
    app.include_router(files.router, dependencies=logged_in)
    app.include_router(categories.router, dependencies=logged_in)
    app.include_router(flags.router, dependencies=logged_in)
    app.include_router(receipts.router, dependencies=logged_in)
    app.include_router(query.router, dependencies=logged_in)
    return app


app = create_app()
