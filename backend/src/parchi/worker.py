"""ARQ worker settings. Run with: arq parchi.worker.WorkerSettings"""

import logging
from typing import Any, ClassVar

from arq import cron

from parchi.config import get_settings
from parchi.db.session import get_engine
from parchi.logging import configure_logging, get_logger
from parchi.pipeline.queue import redis_settings
from parchi.pipeline.tasks import ai_extract_task, process_file_task, recover

log = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings)
    # The arq command line installs its own handler; send its lines through ours only.
    arq_logger = logging.getLogger("arq")
    arq_logger.handlers.clear()
    arq_logger.propagate = True
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    log.info("worker.started", env=settings.app_env.value)


async def shutdown(ctx: dict[str, Any]) -> None:
    await get_engine().dispose()
    log.info("worker.stopped")


class WorkerSettings:
    functions: ClassVar = [process_file_task, ai_extract_task]
    cron_jobs: ClassVar = [cron(recover, second=0, run_at_startup=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    job_timeout = 300  # D-025: a job is stopped after 5 minutes
    max_tries = 1  # retries are handled by the recovery task, with backoff
    keep_result = 0  # so the same file can be queued again once its job is done
    # OCR runs one page at a time anyway; fewer jobs keep memory low (D-034).
    max_jobs = 2
