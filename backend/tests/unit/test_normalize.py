from datetime import date, datetime
from decimal import Decimal

import pytest

from parchi.extraction.normalize import (
    amounts_in,
    clean_receipt_number,
    clean_vendor,
    find_date,
    parse_amount,
    parse_date,
    parse_quantity,
)


@pytest.mark.parametrize(
    ("raw", "amount"),
    [
        ("₹ 1,23,456.50", "123456.50"),  # Indian grouping
        ("Rs. 540/-", "540.00"),
        ("1,234.5 INR", "1234.50"),
        ("(12.00)", "-12.00"),
        ("540", "540.00"),
        (1888.0, "1888.00"),
        (144, "144.00"),
        (0.1 + 0.2, "0.30"),  # a float from a spreadsheet, rounded to paise
    ],
)
def test_amounts_become_exact_decimals(raw: object, amount: str) -> None:
    assert parse_amount(raw) == Decimal(amount)


@pytest.mark.parametrize("raw", [None, "", "abc", "12-08", True, float("nan"), "1.2.3"])
def test_unreadable_amounts_are_none(raw: object) -> None:
    assert parse_amount(raw) is None


def test_amounts_in_a_line_skip_percentages_and_dates() -> None:
    assert amounts_in("CGST @ 9% 45.00") == [Decimal("45.00")]
    assert amounts_in("Grand Total Rs. 2,950.00") == [Decimal("2950.00")]
    assert amounts_in("Invoice INV-0421 dated 14/08/2026") == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("14/08/2026", date(2026, 8, 14)),
        ("03/04/2026", date(2026, 4, 3)),  # day first (D-024)
        ("Date: 14-08-26", date(2026, 8, 14)),
        ("14.08.26", date(2026, 8, 14)),
        ("2026-08-14", date(2026, 8, 14)),
        ("14 Aug 2026 18:42", date(2026, 8, 14)),
        ("14th August, 2026", date(2026, 8, 14)),
        ("14-Sept-2026", date(2026, 9, 14)),
        ("Aug 14, 2026", date(2026, 8, 14)),
    ],
)
def test_dates_are_read_day_first(text: str, expected: date) -> None:
    assert find_date(text) == expected


@pytest.mark.parametrize("text", ["31/02/2026", "no date here", "99/99/99"])
def test_impossible_dates_are_none(text: str) -> None:
    assert find_date(text) is None


def test_spreadsheet_date_cells() -> None:
    assert parse_date(datetime(2026, 8, 14, 10, 30)) == date(2026, 8, 14)
    assert parse_date(date(2026, 8, 14)) == date(2026, 8, 14)


def test_quantities() -> None:
    assert parse_quantity("12.35 L") == Decimal("12.350")
    assert parse_quantity(4) == Decimal("4.000")
    assert parse_quantity("two") is None


def test_receipt_numbers_need_a_digit() -> None:
    assert clean_receipt_number(" ST/2026/0421 ") == "ST/2026/0421"
    assert clean_receipt_number(421.0) == "421"
    assert clean_receipt_number("Amount") is None


def test_vendor_names_are_tidied() -> None:
    assert clean_vendor("  Sharma   Traders, ") == "Sharma Traders"
    assert clean_vendor("   ") is None


def test_rates_with_a_space_before_the_percent_sign_are_not_amounts() -> None:
    assert amounts_in("SGST/UTGST: 9.0 %") == []
    assert amounts_in("CGST: 9.0 % 289.75") == [Decimal("289.75")]
