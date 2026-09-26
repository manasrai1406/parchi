from datetime import date
from decimal import Decimal

import pytest

from parchi.db.enums import FlagType
from parchi.schemas.receipt import LineItemSchema, ReceiptSchema
from parchi.validation.rules import arithmetic_problems, date_problems, financial_year_start

TODAY = date(2026, 9, 26)


def receipt(**fields: object) -> ReceiptSchema:
    base = {
        "vendor": "Sharma Traders",
        "receipt_date": date(2026, 8, 14),
        "total": Decimal("1180.00"),
        "confidence": 1.0,
        "source": "test",
    }
    return ReceiptSchema(**(base | fields))


def items(*amounts: str) -> list[LineItemSchema]:
    return [
        LineItemSchema(description=f"item {i}", amount=Decimal(a)) for i, a in enumerate(amounts)
    ]


def test_a_consistent_receipt_passes() -> None:
    r = receipt(subtotal=Decimal("1000.00"), tax=Decimal("180.00"), line_items=items("600", "400"))
    assert arithmetic_problems(r, 1) == []


def test_round_off_up_to_one_rupee_passes() -> None:
    # 1000.00 + 179.60 = 1179.60, printed total rounded to 1180.
    r = receipt(subtotal=Decimal("1000.00"), tax=Decimal("179.60"))
    assert arithmetic_problems(r, 1) == []


def test_subtotal_plus_tax_must_equal_total() -> None:
    (problem,) = arithmetic_problems(receipt(subtotal=Decimal("1000"), tax=Decimal("100")), 1)
    assert problem.type == FlagType.ARITHMETIC_MISMATCH
    assert "₹1,100.00" in problem.detail and "₹1,180.00" in problem.detail


@pytest.mark.parametrize(
    ("amounts", "ok"),
    [
        (("1000.00",), True),  # items add up to the subtotal
        (("1180.00",), True),  # ... or to the total (tax-inclusive prices)
        (("1180.90",), True),  # within a rupee
        (("900.00",), False),
    ],
)
def test_items_must_add_up_to_subtotal_or_total(amounts: tuple[str, ...], ok: bool) -> None:
    r = receipt(subtotal=Decimal("1000.00"), tax=Decimal("180.00"), line_items=items(*amounts))
    assert (arithmetic_problems(r, 1) == []) is ok


def test_financial_year_starts_on_1_april() -> None:
    assert financial_year_start(date(2026, 9, 26)) == date(2026, 4, 1)
    assert financial_year_start(date(2027, 2, 10)) == date(2026, 4, 1)
    assert financial_year_start(date(2026, 4, 1)) == date(2026, 4, 1)


@pytest.mark.parametrize(
    ("when", "ok"),
    [
        (date(2026, 9, 26), True),  # today
        (date(2025, 4, 1), True),  # first day of last financial year
        (date(2025, 3, 31), False),  # the day before
        (date(2026, 9, 27), False),  # tomorrow
        (date(2062, 8, 14), False),  # a misread year
    ],
)
def test_dates_from_last_financial_year_to_today(when: date, ok: bool) -> None:
    problems = date_problems(receipt(receipt_date=when), 1, TODAY)
    assert (problems == []) is ok
    if not ok:
        assert problems[0].type == FlagType.VALIDATION_FAILED
