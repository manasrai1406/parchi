"""The plain-English question reader (D-037) and the Query filters (D-038, D-039)."""

from datetime import date
from decimal import Decimal

import pytest

from parchi.query.ask import NotUnderstood, read_question, rupees
from parchi.query.filters import safe_cell, statement, to_sql, with_default_dates
from parchi.schemas.api import ReceiptQuery

TODAY = date(2026, 9, 26)
CATEGORIES = [
    (1, "Fuel"),
    (2, "Travel"),
    (3, "Food"),
    (4, "Office"),
    (5, "Utilities"),
    (6, "Maintenance"),
    (7, "Services"),
    (8, "Other"),
    (9, "Client gifts"),
]
VENDORS = [
    "Sector 12 Fuel Station",
    "Ring Road Petrol Pump",
    "Raju Hardware",
    "Blue Tokai Coffee Roasters",
]


def read(question: str):
    return read_question(question, today=TODAY, categories=CATEGORIES, vendors=VENDORS)


def understood(question: str) -> dict[str, str]:
    return {u.label: u.value for u in read(question).understood if u.label != "Status"}


def dates(question: str) -> tuple[date | None, date | None]:
    query = read(question).query
    return query.date_from, query.date_to


def test_fuel_in_august() -> None:
    reading = read("Fuel in August?")
    assert reading.query.category_id == 1
    assert (reading.query.date_from, reading.query.date_to) == (date(2026, 8, 1), date(2026, 8, 31))
    assert reading.ignored == []
    assert understood("fuel in August") == {
        "Category": "Fuel",
        "Dates": "1 Aug 2026 to 31 Aug 2026",
    }
    assert read("fuel in August").understood[-1].value == "Parsed or Resolved"


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("december", (date(2025, 12, 1), date(2025, 12, 31))),  # the latest December
        ("fuel for aug 2025", (date(2025, 8, 1), date(2025, 8, 31))),
        ("in may", (date(2026, 5, 1), date(2026, 5, 31))),
        ("last month", (date(2026, 8, 1), date(2026, 8, 31))),
        ("this month", (date(2026, 9, 1), TODAY)),
        ("this week", (date(2026, 9, 21), TODAY)),
        ("last week", (date(2026, 9, 14), date(2026, 9, 20))),
        ("this financial year", (date(2026, 4, 1), TODAY)),
        ("last financial year", (date(2025, 4, 1), date(2026, 3, 31))),
        ("fy 2025-26", (date(2025, 4, 1), date(2026, 3, 31))),
        ("last year", (date(2025, 1, 1), date(2025, 12, 31))),
        ("in 2026", (date(2026, 1, 1), date(2026, 12, 31))),
        ("today", (TODAY, TODAY)),
        ("yesterday", (date(2026, 9, 25), date(2026, 9, 25))),
        ("last 30 days", (date(2026, 8, 28), TODAY)),
        ("between 1 aug and 15 aug", (date(2026, 8, 1), date(2026, 8, 15))),
        ("from 2026-07-01 to 2026-07-31", (date(2026, 7, 1), date(2026, 7, 31))),
        ("from 1 sept to 30 aug", (date(2025, 9, 1), date(2026, 8, 30))),
        ("on 14/08/2026", (date(2026, 8, 14), date(2026, 8, 14))),
        ("Aug 14, 2026", (date(2026, 8, 14), date(2026, 8, 14))),
        ("since 1st july", (date(2026, 7, 1), TODAY)),
        ("before 1 may 2026", (None, date(2026, 4, 30))),
        ("show me all receipts", (date(2026, 4, 1), TODAY)),  # D-028 default
    ],
)
def test_periods(question: str, expected: tuple) -> None:
    assert dates(question) == expected


def test_the_default_period_says_so() -> None:
    assert understood("receipts")["Dates"].endswith("(default)")


@pytest.mark.parametrize(
    ("question", "low", "high"),
    [
        ("over ₹1,000", "1000", None),
        ("more than rs. 500", "500", None),
        ("at least 2k", "2000", None),
        ("under 500", None, "500"),
        ("less than 99.50 rupees", None, "99.50"),
        ("between 500 and 2000", "500", "2000"),
        ("over 1.5 lakh", "150000", None),
    ],
)
def test_amounts(question: str, low: str | None, high: str | None) -> None:
    query = read(question).query
    assert query.min_total == (Decimal(low) if low else None)
    assert query.max_total == (Decimal(high) if high else None)


def test_amount_labels_use_indian_grouping() -> None:
    assert understood("over 150000")["Amount"] == "₹1,50,000.00 or more"
    assert rupees(Decimal("12345678.5")) == "₹1,23,45,678.50"


@pytest.mark.parametrize(
    ("question", "category_id"),
    [
        ("petrol last month", 1),
        ("taxi rides", 2),
        ("lunch bills", 3),
        ("electricity", 5),
        ("client gifts in july", 9),  # a custom category
    ],
)
def test_categories_by_name_or_word(question: str, category_id: int) -> None:
    assert read(question).query.category_id == category_id


def test_one_category_at_a_time() -> None:
    with pytest.raises(NotUnderstood, match="one category at a time"):
        read("fuel and food")


def test_one_period_at_a_time() -> None:
    with pytest.raises(NotUnderstood, match="one period at a time"):
        read("fuel in august last month")


def test_vendor_by_full_name_is_not_taken_for_a_category() -> None:
    query = read("spent at sector 12 fuel station in may").query
    assert (query.vendor, query.category_id) == ("Sector 12 Fuel Station", None)


def test_vendor_by_the_start_of_its_name() -> None:
    assert read("receipts from raju").query.vendor == "Raju Hardware"
    assert read("at least 500 from ring road").query.vendor == "Ring Road Petrol Pump"


def test_order_and_top_n() -> None:
    top = read("top 5 receipts this financial year").query
    assert (top.sort, top.limit) == ("amount", 5)
    assert read("3 largest lunch bills").query.limit == 3
    biggest = read("biggest receipts").query
    assert (biggest.sort, biggest.limit) == ("amount", None)
    assert understood("top 5")["Order"] == "Largest first, top 5"


def test_may_as_a_verb_is_not_a_month() -> None:
    reading = read("may I see fuel")
    assert reading.query.date_from == date(2026, 4, 1)  # the default, not May
    assert reading.ignored == ["may", "see"]


def test_unknown_words_are_listed_back() -> None:
    assert read("fuel in august urgently").ignored == ["urgently"]


def test_nothing_understood_gives_examples() -> None:
    with pytest.raises(NotUnderstood, match="fuel in August"):
        read("hello world")


def test_a_backwards_range_is_explained() -> None:
    with pytest.raises(NotUnderstood, match="From cannot be later than To"):
        read("from 1 sept 2026 to 1 aug 2026")


def test_an_impossible_date_is_explained() -> None:
    with pytest.raises(NotUnderstood, match="not a real date"):
        read("on 31/02/2026")


# --- filters -----------------------------------------------------------------------------


def test_no_dates_means_the_financial_year_to_date() -> None:
    query = with_default_dates(ReceiptQuery(), TODAY)
    assert (query.date_from, query.date_to) == (date(2026, 4, 1), TODAY)
    before_april = with_default_dates(ReceiptQuery(), date(2027, 2, 10))
    assert before_april.date_from == date(2026, 4, 1)
    only_to = with_default_dates(ReceiptQuery(date_to=date(2026, 5, 1)), TODAY)
    assert only_to.date_from is None


def test_sql_only_counts_parsed_and_resolved_files() -> None:
    sql = to_sql(statement(ReceiptQuery(date_from=date(2026, 8, 1), date_to=date(2026, 8, 31))))
    assert "status IN ('parsed', 'resolved')" in sql
    assert "BETWEEN '2026-08-01' AND '2026-08-31'" in sql
    assert sql.endswith(";")


def test_values_are_quoted_in_the_sql_shown() -> None:
    sql = to_sql(statement(ReceiptQuery(vendor="O'Brien'; DROP TABLE files; --")))
    assert "'O''Brien''; DROP TABLE files; --'" in sql


@pytest.mark.parametrize(
    ("value", "cell"),
    [
        ("=SUM(A1)", "'=SUM(A1)"),
        ("+91 shop", "'+91 shop"),
        ("-x", "'-x"),
        ("@cmd", "'@cmd"),
        ("Raju Hardware", "Raju Hardware"),
        (None, ""),
        (Decimal("-5.00"), Decimal("-5.00")),  # amounts stay numbers
    ],
)
def test_csv_cells_cannot_be_formulas(value: object, cell: object) -> None:
    assert safe_cell(value) == cell


def test_bad_filter_ranges_are_refused() -> None:
    with pytest.raises(ValueError, match="From cannot be later than To"):
        ReceiptQuery(date_from=date(2026, 9, 1), date_to=date(2026, 8, 1))
    with pytest.raises(ValueError, match="minimum amount"):
        ReceiptQuery(min_total=Decimal(10), max_total=Decimal(5))
