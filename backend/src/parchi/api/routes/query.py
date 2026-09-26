"""Plain-English questions, read by rules (D-037) and run on read-only access (D-038)."""

from fastapi import APIRouter
from sqlalchemy import select

from parchi.api.deps import SessionDep
from parchi.api.errors import AppError, ErrorResponse
from parchi.api.routes.receipts import list_vendors, receipt_page
from parchi.db.models import Category
from parchi.logging import get_logger
from parchi.query import filters
from parchi.query.ask import NotUnderstood, read_question
from parchi.schemas.api import AskIn, AskOut
from parchi.validation.rules import current_date

router = APIRouter(prefix="/query", tags=["query"])
log = get_logger(__name__)


@router.post("/ask", responses={422: {"model": ErrorResponse}})
async def ask(body: AskIn, session: SessionDep) -> AskOut:
    """How the question was read, the SQL that ran, and the first page of receipts.

    Nothing is sent to an AI provider. Later pages come from `GET /receipts` with the
    returned `filters`.
    """
    categories = [tuple(row) for row in await session.execute(select(Category.id, Category.name))]
    vendors = await list_vendors(session)
    try:
        reading = read_question(
            body.question, today=current_date(), categories=categories, vendors=vendors
        )
    except NotUnderstood as exc:
        log.info("query.not_understood")
        raise AppError(422, "question_not_understood", str(exc)) from exc

    # Logs say what kind of filters were used, never the question or its values.
    log.info("query.asked", understood=[item.label for item in reading.understood])
    return AskOut(
        question=body.question,
        understood_as=reading.understood,
        ignored=reading.ignored,
        filters=reading.query,
        sql=filters.to_sql(filters.statement(reading.query)),
        result=await receipt_page(session, reading.query),
    )
