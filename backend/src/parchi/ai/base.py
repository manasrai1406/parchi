"""One interface for every AI provider (plan phase 6, D-035).

A provider can only be called with an `Approval`, and an Approval can only be made from
an extraction run that records who approved it, when, and for which provider (hard rule
1, D-036). Nothing else in Parchi talks to an AI provider.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from parchi.db.enums import AiProvider, RunParser


class ApprovalMissingError(RuntimeError):
    """An AI call was attempted without a recorded approval. Never caught quietly."""


class AiCallError(Exception):
    """The provider could not produce a result. The message is safe to show and log:
    it never contains receipt content."""


@dataclass(frozen=True)
class Approval:
    run_id: int
    provider: AiProvider
    model: str
    approved_by: str
    approved_at: datetime

    @classmethod
    def from_run(cls, run: Any) -> "Approval":
        """The only way to make an Approval: from a run that carries one."""
        if (
            run.parser != RunParser.AI
            or run.provider is None
            or not run.model
            or not run.ai_approved_by
            or run.ai_approved_at is None
        ):
            raise ApprovalMissingError(f"Run {run.id} has no recorded AI approval.")
        return cls(run.id, run.provider, run.model, run.ai_approved_by, run.ai_approved_at)


@dataclass(frozen=True)
class AiInput:
    """What is sent: exactly one of an image, a PDF, or text from a spreadsheet (D-035)."""

    filename: str
    image: bytes | None = None
    image_type: str | None = None  # image/jpeg, image/png, image/webp
    pdf: bytes | None = None
    text: str | None = None


@dataclass(frozen=True)
class AiOutput:
    data: dict[str, Any]  # JSON matching RECEIPTS_SCHEMA
    input_tokens: int | None
    output_tokens: int | None
    request_id: str | None


class Provider(Protocol):
    name: AiProvider
    model: str

    async def extract(self, approval: Approval, item: AiInput) -> AiOutput: ...
