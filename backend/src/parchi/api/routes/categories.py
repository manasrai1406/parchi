"""Categories: eight built-in ones plus any people add (D-026)."""

from typing import Any

from fastapi import APIRouter, Response
from fastapi import status as http_status
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError

from parchi.api.deps import SessionDep
from parchi.api.errors import AppError, ErrorResponse
from parchi.auth.deps import Reviewer
from parchi.db.models import Category, Receipt, Vendor
from parchi.logging import get_logger
from parchi.schemas.api import CategoryIn, CategoryOut

router = APIRouter(prefix="/categories", tags=["categories"])
log = get_logger(__name__)

ERRORS = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}}


def _uses(category_id: Any) -> tuple[Any, Any]:
    """How many receipts and vendors use a category: counts for an id, or correlated
    subqueries when given the Category.id column."""
    receipts = (
        select(func.count())
        .select_from(Receipt)
        .where(
            or_(
                Receipt.category_auto_id == category_id,
                Receipt.category_override_id == category_id,
            )
        )
        .scalar_subquery()
    )
    vendors = (
        select(func.count())
        .select_from(Vendor)
        .where(Vendor.default_category_id == category_id)
        .scalar_subquery()
    )
    return receipts, vendors


async def _out(session: SessionDep, category: Category) -> CategoryOut:
    receipts, vendors = _uses(category.id)
    in_use = await session.scalar(select(receipts + vendors))
    return CategoryOut(
        id=category.id, name=category.name, builtin=category.builtin, in_use=in_use or 0
    )


async def _get(session: SessionDep, category_id: int) -> Category:
    category = await session.get(Category, category_id)
    if category is None:
        raise AppError(404, "category_not_found", "Category not found.")
    return category


async def _name_taken(session: SessionDep, name: str, except_id: int | None = None) -> bool:
    query = select(Category.id).where(func.lower(Category.name) == name.lower())
    if except_id is not None:
        query = query.where(Category.id != except_id)
    return (await session.scalar(query)) is not None


def _exists(name: str) -> AppError:
    return AppError(409, "category_exists", f'A category called "{name}" already exists.')


@router.get("")
async def list_categories(session: SessionDep) -> list[CategoryOut]:
    """Built-in categories first, in their usual order, then custom ones A to Z."""
    receipts, vendors = _uses(Category.id)
    rows = await session.execute(
        select(Category, receipts + vendors).order_by(
            Category.builtin.desc(),
            case((Category.builtin, Category.id), else_=None),
            func.lower(Category.name),
        )
    )
    return [CategoryOut(id=c.id, name=c.name, builtin=c.builtin, in_use=count) for c, count in rows]


@router.post("", status_code=http_status.HTTP_201_CREATED, responses=ERRORS)
async def create_category(body: CategoryIn, session: SessionDep, _: Reviewer) -> CategoryOut:
    if await _name_taken(session, body.name):
        raise _exists(body.name)
    category = Category(name=body.name)
    session.add(category)
    try:
        await session.commit()
    except IntegrityError as exc:  # created by someone else a moment ago
        raise _exists(body.name) from exc
    log.info("category.created", category_id=category.id)
    return await _out(session, category)


@router.patch("/{category_id}", responses=ERRORS)
async def rename_category(
    category_id: int, body: CategoryIn, session: SessionDep, _: Reviewer
) -> CategoryOut:
    category = await _get(session, category_id)
    if category.builtin:
        raise AppError(409, "builtin_category", "Built-in categories cannot be renamed.")
    if await _name_taken(session, body.name, except_id=category_id):
        raise _exists(body.name)
    category.name = body.name
    try:
        await session.commit()
    except IntegrityError as exc:
        raise _exists(body.name) from exc
    log.info("category.renamed", category_id=category_id)
    return await _out(session, category)


@router.delete("/{category_id}", status_code=http_status.HTTP_204_NO_CONTENT, responses=ERRORS)
async def delete_category(category_id: int, session: SessionDep, _: Reviewer) -> Response:
    """Only custom categories that no receipt or vendor uses."""
    category = await _get(session, category_id)
    if category.builtin:
        raise AppError(409, "builtin_category", "Built-in categories cannot be deleted.")
    receipts_q, vendors_q = _uses(category_id)
    receipts = await session.scalar(select(receipts_q))
    vendors = await session.scalar(select(vendors_q))
    if receipts or vendors:
        raise AppError(
            409,
            "category_in_use",
            f"This category is used by {receipts} receipt(s) and {vendors} vendor(s). "
            "Move them to another category first.",
        )
    await session.delete(category)
    try:
        await session.commit()
    except IntegrityError as exc:  # put to use a moment ago
        raise AppError(409, "category_in_use", "This category is in use.") from exc
    log.info("category.deleted", category_id=category_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
