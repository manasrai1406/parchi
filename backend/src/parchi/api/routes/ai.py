"""Opt-in AI (hard rule 1, D-036): approve files for an AI read, and today's usage."""

from fastapi import APIRouter, status

from parchi.ai import providers
from parchi.api.deps import SessionDep, SettingsDep
from parchi.api.errors import AppError, ErrorResponse
from parchi.db.enums import AiProvider
from parchi.db.repositories import get_file
from parchi.pipeline import ai
from parchi.pipeline.queue import queue_ai_runs
from parchi.schemas.api import (
    AiBatchIn,
    AiExtractIn,
    AiProviderInfo,
    AiRunOut,
    AiRunsOut,
    AiUsage,
)

router = APIRouter(tags=["ai"])

REFUSALS = {
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
}


async def _approve(
    keys: list[str], body: AiExtractIn, session: SessionDep, settings: SettingsDep
) -> AiRunsOut:
    files = []
    for key in dict.fromkeys(keys):  # a file named twice is approved once
        file = await get_file(session, key)
        if file is None:
            raise AppError(404, "file_not_found", f"File not found: {key}")
        files.append(file)
    refs = {file.id: file.ref_no for file in files}
    await session.rollback()
    label = providers.LABELS[body.provider]
    try:
        run_ids = await ai.approve(session, list(refs), body.provider, settings)
    except ai.AiDisabledError as exc:
        raise AppError(
            403, "ai_disabled", "AI is switched off. Set AI_ENABLED=true to allow approved reads."
        ) from exc
    except providers.ProviderNotConfiguredError as exc:
        raise AppError(409, "provider_not_configured", f"No API key is set for {label}.") from exc
    except ai.DailyCapReachedError as exc:
        raise AppError(
            429,
            "daily_cap_reached",
            f"Today's AI limit ({settings.ai_daily_cap}) allows {exc.remaining} more.",
        ) from exc
    except ai.NotEligibleError as exc:
        raise AppError(
            409,
            "not_eligible",
            f"{exc.ref_no} is {exc.status.value.replace('_', ' ')}: only files that need review, "
            "are flagged or are parsed can be sent to AI.",
        ) from exc
    await queue_ai_runs(run_ids)
    return AiRunsOut(
        runs=[
            AiRunOut(file_id=file_id, ref_no=refs[file_id], run_id=run_id)
            for file_id, run_id in zip(refs, run_ids, strict=True)
        ]
    )


@router.post("/files/ai-extract", status_code=status.HTTP_202_ACCEPTED, responses=REFUSALS)
async def ai_extract_batch(
    body: AiBatchIn, session: SessionDep, settings: SettingsDep
) -> AiRunsOut:
    """Approve several files for an AI read. All or nothing."""
    return await _approve(body.files, body, session, settings)


@router.post(
    "/files/{file_key}/ai-extract", status_code=status.HTTP_202_ACCEPTED, responses=REFUSALS
)
async def ai_extract(
    file_key: str, body: AiExtractIn, session: SessionDep, settings: SettingsDep
) -> AiRunsOut:
    """Approve one file for an AI read. The approval is recorded before anything is sent."""
    return await _approve([file_key], body, session, settings)


@router.get("/ai/usage")
async def ai_usage(session: SessionDep, settings: SettingsDep) -> AiUsage:
    """For the sidebar: approved AI reads today against the daily cap, and the providers."""
    used = await ai.used_today(session, settings)
    return AiUsage(
        enabled=settings.ai_enabled,
        daily_cap=settings.ai_daily_cap,
        used_today=used,
        remaining=max(settings.ai_daily_cap - used, 0),
        providers=[
            AiProviderInfo(
                provider=provider,
                label=providers.LABELS[provider],
                model=providers.model_for(provider, settings),
                configured=providers.is_configured(provider, settings),
            )
            for provider in AiProvider
        ],
    )
