"""Turn printed values into typed ones: amounts to Decimal, dates to date (stage 5).

Anything that cannot be read with confidence becomes None. Nothing here guesses.
"""

import math
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_MONTH = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)

# Day-first numeric dates (D-024): 14/08/2026, 14-08-26, 14.08.2026
_DMY = re.compile(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})(?!\d)")
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
# 14 Aug 2026, 14-Aug-26, 14th August, 2026
_D_MON_Y = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s\-/.]*{_MONTH}\.?[\s\-/.,]*(\d{{4}}|\d{{2}})(?!\d)",
    re.IGNORECASE,
)
# Aug 14, 2026
_MON_D_Y = re.compile(
    rf"\b{_MONTH}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)", re.IGNORECASE
)

DATE_PATTERN = (
    r"(?:\d{1,2}[/\-.]\d{1,2}[/\-.](?:\d{4}|\d{2})"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?[\s\-/.]*{_MONTH}\.?[\s\-/.,]*(?:\d{{4}}|\d{{2}})"
    rf"|{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})"
)

_CURRENCY = re.compile(r"₹|\brs\b\.?|\binr\b|/-", re.IGNORECASE)
_PLAIN_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
# An amount inside a line of text: 1,23,456.50 or 540 or 540.5, with an optional ₹/Rs.
AMOUNT_IN_TEXT = re.compile(
    r"(?<![\w.,/-])(?:₹|rs\.?|inr)?\s*(\(?-?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d{1,2})?\)?)(?![\d,]*\d|\.\d|[/-]\d|\s*%)",
    re.IGNORECASE,
)

TWO_PLACES = Decimal("0.01")


def clean_text(value: Any) -> str | None:
    """Collapse whitespace; empty becomes None."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = " ".join(str(value).split())
    return text or None


def _to_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_amount(value: Any) -> Decimal | None:
    """A money value, rounded to paise. Accepts spreadsheet numbers and printed text."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        amount = Decimal(repr(value))
    else:
        text = _CURRENCY.sub("", str(value)).strip()
        negative = text.startswith("(") and text.endswith(")")
        text = text.strip("()").replace(",", "").replace(" ", "")
        if not _PLAIN_NUMBER.match(text):
            return None
        amount = _to_decimal(text)
        if amount is None:
            return None
        if negative:
            amount = -amount
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def parse_quantity(value: Any) -> Decimal | None:
    """A quantity such as 2, 1.5 or '12.35 L'. Up to three decimal places."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return None if math.isnan(value) else Decimal(repr(value)).quantize(Decimal("0.001"))
    if isinstance(value, int | Decimal):
        return Decimal(value).quantize(Decimal("0.001"))
    text = clean_text(value)
    if text is None:
        return None
    match = re.match(r"^(\d+(?:\.\d+)?)", text.replace(",", ""))
    return Decimal(match.group(1)).quantize(Decimal("0.001")) if match else None


def amounts_in(text: str) -> list[Decimal]:
    """Every amount printed in a line, left to right."""
    found = []
    for match in AMOUNT_IN_TEXT.finditer(text):
        amount = parse_amount(match.group(1))
        if amount is not None:
            found.append(amount)
    return found


def _safe_date(year: int, month: int, day: int) -> date | None:
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_date(text: str) -> date | None:
    """The first readable date in a piece of text, read day-first (D-024)."""
    candidates: list[tuple[int, date]] = []
    for match in _ISO.finditer(text):
        if parsed := _safe_date(int(match[1]), int(match[2]), int(match[3])):
            candidates.append((match.start(), parsed))
    for match in _DMY.finditer(text):
        if parsed := _safe_date(int(match[3]), int(match[2]), int(match[1])):
            candidates.append((match.start(), parsed))
    for match in _D_MON_Y.finditer(text):
        month = MONTHS[match[2].lower()[:3]]
        if parsed := _safe_date(int(match[3]), month, int(match[1])):
            candidates.append((match.start(), parsed))
    for match in _MON_D_Y.finditer(text):
        month = MONTHS[match[1].lower()[:3]]
        if parsed := _safe_date(int(match[3]), month, int(match[2])):
            candidates.append((match.start(), parsed))
    return min(candidates)[1] if candidates else None


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "to_pydatetime"):  # pandas Timestamp
        try:
            return value.to_pydatetime().date()
        except (ValueError, OverflowError):
            return None
    text = clean_text(value)
    return find_date(text) if text else None


def clean_receipt_number(value: Any) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    text = text.strip(" :#.-")
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    # A receipt number always has a digit; a word next to "Bill No" is a header.
    if not any(ch.isdigit() for ch in text):
        return None
    return text[:64] or None


def clean_vendor(value: Any) -> str | None:
    """The printed vendor name with spacing and stray punctuation tidied (D-024)."""
    text = clean_text(value)
    if text is None:
        return None
    text = text.strip(" :,-|*")
    return text[:255] or None
