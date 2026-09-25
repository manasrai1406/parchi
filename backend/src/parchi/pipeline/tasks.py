"""The worker's jobs."""

from typing import Any

from parchi.config import get_settings
from parchi.db.session import get_sessionmaker
from parchi.ingestion.storage import Storage
from parchi.logging import bind_context, clear_context, get_logger
from parchi.pipeline.orchestrator import process_file
from parchi.pipeline.queue import enqueue_file
from parchi.pipeline.recovery import files_to_queue

log = get_logger(__name__)


async def process_file_task(ctx: dict[str, Any], file_id: int) -> str:
    clear_context()
    bind_context(file_id=file_id)
    try:
        storage = Storage(get_settings().storage_dir)
        outcome = await process_file(get_sessionmaker(), storage, file_id)
        return outcome.value
    finally:
        clear_context()


async def recover(ctx: dict[str, Any]) -> int:
    """Every minute: queue pending files, reset stuck ones, retry failed ones."""
    async with get_sessionmaker()() as session:
        file_ids = await files_to_queue(session)
    queued = 0
    for file_id in file_ids:
        queued += await enqueue_file(ctx["redis"], file_id)
    if file_ids:
        log.info("recovery.queued", candidates=len(file_ids), queued=queued)
    return queued
