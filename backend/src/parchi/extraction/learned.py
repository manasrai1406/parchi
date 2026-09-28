"""Labels people taught the reader, used after the built-in ones (D-048).

The built-in labels (labels.py) are tried first. When a receipt still has no total,
subtotal or tax, the labels learned for its vendor are tried on the text it was read
from, then labels learned from three or more vendors.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from parchi.db.models import LEARNED_FIELDS, Vendor, VendorLabel
from parchi.extraction.grid import confidence_of
from parchi.extraction.labels import match_label, normalize_label, split_labelled
from parchi.extraction.normalize import amounts_in, clean_vendor
from parchi.schemas.receipt import ReceiptSchema

# A label learned for this many vendors is used for every receipt.
GLOBAL_AFTER = 3


@dataclass(frozen=True)
class Found:
    field: str
    label: str
    amount: Decimal


async def vendor_key(session: AsyncSession, printed: str | None) -> str | None:
    """The vendor's normalized name in lower case, as receipts are grouped (D-027)."""
    if not printed:
        return None
    raw = clean_vendor(printed) or printed.strip()
    normalized = await session.scalar(
        select(Vendor.normalized_name).where(func.lower(Vendor.raw_name) == raw.lower()).limit(1)
    )
    key = (normalized or raw).strip().lower()
    return key or None


def find(text: str, labels: dict[str, list[str]]) -> list[Found]:
    """Amounts after the given labels in a receipt's text, one per field (the first line)."""
    found: dict[str, Found] = {}
    for line in text.splitlines():
        for part in split_labelled(line):
            match = match_label(part, labels)
            if match is None or match.field in found:
                continue
            amounts = amounts_in(match.rest)
            if amounts:
                found[match.field] = Found(match.field, match.label, amounts[-1])
    return list(found.values())


async def _labels_for(session: AsyncSession, keys: set[str]) -> tuple[dict, dict]:
    """Labels per vendor, and labels every receipt may use."""
    by_vendor: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    if keys:
        rows = await session.execute(
            select(VendorLabel.vendor_key, VendorLabel.field, VendorLabel.label).where(
                VendorLabel.vendor_key.in_(keys)
            )
        )
        for key, field, label in rows:
            by_vendor[key][field].append(label)
    shared: dict[str, list[str]] = defaultdict(list)
    rows = await session.execute(
        select(VendorLabel.field, VendorLabel.label)
        .group_by(VendorLabel.field, VendorLabel.label)
        .having(func.count(func.distinct(VendorLabel.vendor_key)) >= GLOBAL_AFTER)
    )
    for field, label in rows:
        shared[field].append(label)
    return by_vendor, shared


async def apply_learned(
    session: AsyncSession, receipts: list[ReceiptSchema]
) -> list[ReceiptSchema]:
    """Fill a missing total, subtotal or tax from learned labels. The caller commits."""
    wanting = [
        r for r in receipts if r.text and any(getattr(r, field) is None for field in LEARNED_FIELDS)
    ]
    if not wanting:
        return receipts
    keys = {r: await vendor_key(session, r.vendor) for r in wanting}
    by_vendor, shared = await _labels_for(session, {k for k in keys.values() if k})
    if not by_vendor and not shared:
        return receipts

    result = []
    for receipt in receipts:
        if receipt not in keys:
            result.append(receipt)
            continue
        key = keys[receipt]
        labels = {
            field: sorted(
                set(by_vendor.get(key, {}).get(field, [])) | set(shared.get(field, [])),
                key=len,
                reverse=True,
            )
            for field in LEARNED_FIELDS
            if getattr(receipt, field) is None
        }
        found = find(receipt.text or "", {f: labels_ for f, labels_ in labels.items() if labels_})
        if not found:
            result.append(receipt)
            continue
        changes = {item.field: item.amount for item in found}
        before = receipt.model_dump()
        after = before | changes
        base = confidence_of(before)
        # Keep what OCR's certainty did to the confidence (D-032 item 6).
        scale = receipt.confidence / base if base else 1.0
        confidence = round(min(confidence_of(after) * scale, 1.0), 3)
        result.append(receipt.model_copy(update={**changes, "confidence": confidence}))
        # Counted on the vendor's own lesson; a shared label used for a new vendor is not.
        if key:
            await session.execute(
                update(VendorLabel)
                .where(
                    VendorLabel.vendor_key == key,
                    VendorLabel.label.in_([item.label for item in found]),
                )
                .values(times_used=VendorLabel.times_used + 1)
            )
    return result


def label_before(part: str) -> str | None:
    """The words in front of the first amount: 'Agreegate: Rs 212.40' -> 'agreegate'."""
    head = re.split(r"(?:₹|\brs\.?|\binr)?\s*\d", part, maxsplit=1, flags=re.IGNORECASE)[0]
    label = normalize_label(head)
    label = re.sub(r"\s*\b(rs|inr)$", "", label).strip(" -:()[]")
    if not re.search(r"[a-z]", label) or not 2 <= len(label) <= 60:
        return None
    return label


def builtin_field(label: str) -> str | None:
    """The field a label already means, if it is one of the built-in labels."""
    match = match_label(label)
    return match.field if match is not None and match.label == label else None
