"""Labels and lines that hold several amounts (D-047), on text laid out like real receipts."""

from datetime import date
from decimal import Decimal

import pytest

from parchi.extraction.labels import match_label, split_labelled
from parchi.extraction.pdf_text import Page, read_group

# Laid out like a cinema ticket as OCR reads it. A real one prompted D-047; only its
# layout is copied here, with made-up names, numbers and amounts.
CINEMA_TICKET = """H/004421
Sr. No. 001234 Bill.No. 556677
SCREEN 3
SAMPLE CINEMAS CITY CENTRE MALL
Movie SAMPLE FILM (U)
Class: GOLD
Date Saturday 15 Aug 2026
Time 07:30 PM
Row C Seat 7
Net: 180.00 CGST : Rs 16.20 SGST : Rs 16.20
Agreegate: Rs 212.40
Trans No. 1112223 Show No: - 3 User No: 2001"""


def test_a_cinema_ticket_gives_its_total_net_and_tax() -> None:
    receipt = read_group([Page(number=1, text=CINEMA_TICKET, tables=[])])

    assert receipt is not None
    assert receipt.total == Decimal("212.40")
    assert receipt.subtotal == Decimal("180.00")
    assert receipt.tax == Decimal("32.40")  # CGST + SGST
    assert receipt.receipt_number == "556677"
    assert receipt.receipt_date == date(2026, 8, 15)


@pytest.mark.parametrize("label", ["Agreegate", "Aggregate", "AGGREGATE AMOUNT"])
def test_aggregate_is_a_total(label: str) -> None:
    match = match_label(f"{label}: Rs 212.40")
    assert match is not None and match.field == "total"


def test_net_alone_is_the_amount_before_tax_but_net_amount_is_the_total() -> None:
    assert match_label("Net: 180.00").field == "subtotal"  # type: ignore[union-attr]
    assert match_label("Net Amount: 212.40").field == "total"  # type: ignore[union-attr]
    assert match_label("Net Payable 212").field == "total"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("line", "parts"),
    [
        (
            "Net: 180.00 CGST : Rs 16.20 SGST : Rs 16.20",
            ["Net: 180.00", "CGST : Rs 16.20", "SGST : Rs 16.20"],
        ),
        ("Sub Total 500 GST 90 Total 590", ["Sub Total 500", "GST 90", "Total 590"]),
        # A label only starts a new part after a number, and only as a whole word.
        ("CGST @ 9% 45.00", ["CGST @ 9% 45.00"]),
        ("Total 2 items 590.00", ["Total 2 items 590.00"]),
        ("Paid 500 totally", ["Paid 500 totally"]),
        ("Invoice No 1234 Date 14/08/2026", ["Invoice No 1234 Date 14/08/2026"]),
    ],
)
def test_lines_with_several_amounts_are_split(line: str, parts: list[str]) -> None:
    assert split_labelled(line) == parts
