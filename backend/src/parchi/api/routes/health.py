"""Liveness and readiness checks."""

import asyncio
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text

from parchi.api.errors import AppError, ErrorResponse
from parchi.config import get_settings
from parchi.db.session import get_engine
from parchi.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)

CHECK_TIMEOUT_SECONDS = 2.0


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]
    redis: Literal["ok"]


@router.get("/health")
async def health() -> HealthResponse:
    """The API process is up. Does not touch PostgreSQL or Redis."""
    return HealthResponse(status="ok")


async def _check_database() -> None:
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _check_redis() -> None:
    client = Redis.from_url(get_settings().redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()


@router.get("/health/ready", responses={503: {"model": ErrorResponse}})
async def ready() -> ReadyResponse:
    """PostgreSQL and Redis are both reachable."""
    failed = []
    for name, check in (("database", _check_database), ("redis", _check_redis)):
        try:
            await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
        except Exception as exc:
            log.warning("health.check_failed", component=name, error_type=type(exc).__name__)
            failed.append(name)
    if failed:
        raise AppError(503, "not_ready", "Unavailable: " + ", ".join(failed))
    return ReadyResponse(status="ok", database="ok", redis="ok")
