"""Find files that need (re)queueing (hard rule 5, D-025)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# A job is stopped after 5 minutes, so 10 minutes in processing means a worker died.
STUCK_AFTER_SECONDS = 600
# Give the API time to queue a fresh upload itself before recovery does.
PENDING_GRACE_SECONDS = 30
# Failed files wait attempts x this long before the next try, up to MAX_ATTEMPTS tries.
RETRY_BACKOFF_SECONDS = 60
MAX_ATTEMPTS = 3

_RESET_STUCK = text(
    "UPDATE files SET status = 'pending', status_changed_at = now()"
    " WHERE status = 'processing'"
    "   AND status_changed_at < now() - make_interval(secs => :stuck)"
)
_DUE = text(
    "SELECT id FROM files"
    " WHERE (status = 'pending'"
    "        AND status_changed_at < now() - make_interval(secs => :grace))"
    "    OR (status = 'failed' AND attempts < :max_attempts"
    "        AND status_changed_at < now() - make_interval(secs => attempts * :backoff))"
    " ORDER BY id"
)


async def files_to_queue(session: AsyncSession) -> list[int]:
    """Reset stuck files to pending, then list pending files and failed files due a retry."""
    async with session.begin():
        await session.execute(_RESET_STUCK, {"stuck": STUCK_AFTER_SECONDS})
        rows = await session.execute(
            _DUE,
            {
                "grace": PENDING_GRACE_SECONDS,
                "max_attempts": MAX_ATTEMPTS,
                "backoff": RETRY_BACKOFF_SECONDS,
            },
        )
        return [row[0] for row in rows]


_UNFINISHED_AI = text(
    "SELECT id FROM extraction_runs"
    " WHERE parser = 'ai' AND finished_at IS NULL"
    "   AND created_at < now() - make_interval(secs => :stuck)"
    " ORDER BY id"
)


async def ai_runs_to_queue(session: AsyncSession) -> list[int]:
    """Approved AI reads a crashed worker never finished. Their approval is already
    recorded, so they are simply queued again (the job skips a finished run)."""
    async with session.begin():
        rows = await session.execute(_UNFINISHED_AI, {"stuck": STUCK_AFTER_SECONDS})
        return [row[0] for row in rows]
