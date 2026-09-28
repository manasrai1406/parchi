"""Learning a vendor's labels from a person's correction (D-048).

When someone saves a total, subtotal or tax that the reader missed or got wrong, the
file's text is searched for the line holding that amount. The words in front of it
become a label for that vendor, if exactly one such line is found and the words do not
already mean something else.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from parchi.db.enums import LIBRARY_PARSERS
from parchi.db.models import LEARNED_FIELDS, ExtractionRun, VendorLabel
from parchi.extraction.labels import split_labelled
from parchi.extraction.learned import builtin_field, label_before, vendor_key
from parchi.extraction.normalize import amounts_in
from parchi.logging import get_logger
from parchi.schemas.api import ReceiptIn

log = get_logger(__name__)


@dataclass(frozen=True)
class Lesson:
    vendor: str
    field: str
    label: str


def lesson_for(text: str, amount: Decimal) -> str | None:
    """The one label in front of `amount` in the text, or None if none or several."""
    labels = set()
    for line in text.splitlines():
        for part in split_labelled(line):
            if amount in amounts_in(part):
                label = label_before(part)
                if label is not None:
                    labels.add(label)
    if len(labels) != 1:
        return None
    label = labels.pop()
    known = builtin_field(label)
    # A built-in label for another field ("Net" is the subtotal) is not relearned.
    return None if known is not None else label


async def learn(
    session: AsyncSession, file_id: int, receipts: list[ReceiptIn], user: str
) -> list[Lesson]:
    """Record what this correction teaches. The caller commits."""
    run = await session.scalar(
        select(ExtractionRun)
        .where(ExtractionRun.file_id == file_id, ExtractionRun.parser.in_(LIBRARY_PARSERS))
        .options(undefer(ExtractionRun.text))
    )
    if run is None or not run.text:
        return []
    read = run.result_json or []

    lessons: list[Lesson] = []
    for index, receipt in enumerate(receipts):
        before = read[index] if index < len(read) else {}
        key = await vendor_key(session, receipt.vendor)
        if key is None:
            continue
        for field in LEARNED_FIELDS:
            value = getattr(receipt, field)
            if value is None:
                continue
            was = before.get(field)
            if was is not None and Decimal(str(was)) == value:
                continue  # the reader already had it right
            label = lesson_for(run.text, value)
            if label is None:
                continue
            added = await session.scalar(
                insert(VendorLabel)
                .values(
                    vendor_key=key,
                    field=field,
                    label=label,
                    taught_by=user,
                    taught_from_run_id=run.id,
                )
                .on_conflict_do_nothing()
                .returning(VendorLabel.id)
            )
            if added is not None:
                lessons.append(Lesson(vendor=receipt.vendor, field=field, label=label))
    if lessons:
        # Field names only: labels and vendors come from receipt text (hard rule 8).
        log.info("review.learned", fields=[lesson.field for lesson in lessons])
    return lessons
