"""Queueing files for the worker (D-025).

Queueing never blocks an upload: if Redis is down the file stays pending and the
recovery task queues it later.
"""

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from parchi.config import get_settings
from parchi.logging import get_logger

log = get_logger(__name__)

PROCESS_FILE = "process_file_task"

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    settings = RedisSettings.from_dsn(get_settings().redis_url)
    settings.conn_timeout = 2
    settings.conn_retries = 1
    return settings


def job_id(file_id: int) -> str:
    """One job per file at a time: queueing it again while queued does nothing."""
    return f"process-{file_id}"


async def enqueue_file(redis: ArqRedis, file_id: int) -> bool:
    job = await redis.enqueue_job(PROCESS_FILE, file_id, _job_id=job_id(file_id))
    return job is not None


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def queue_file(file_id: int) -> None:
    """Queue a newly registered file. A failure is logged, not raised."""
    try:
        queued = await enqueue_file(await get_pool(), file_id)
        log.info("queue.file_queued", queued_file_id=file_id, already_queued=not queued)
    except Exception as exc:
        log.warning("queue.unavailable", queued_file_id=file_id, error_type=type(exc).__name__)
        await close_pool()
