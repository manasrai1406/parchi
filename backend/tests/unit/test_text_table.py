from decimal import Decimal

from parchi.extraction.text_table import header_columns, read_text_table

LINES = [
    "Total items: 1",
    "Product Title Qty Gross Discounts Taxable SGST CGST Total",
    "Amount /Coupons Value /UTGST",
    "Wireless earbuds with 1 3799.00 0.00 3219.50 289.75 289.75 3799.00",
    "FSN: ABC123 55dB ANC",
    "Handling Fee 1 49.00 -49.00 0.00 0.00 0.00 0.00",
    "SGST/UTGST: 9.0 %",
    "Total 1 3848.00 -49.00 3219.50 289.75 289.75 3799.00",
    "Grand Total 3799.00",
]


def test_header_names_the_numeric_columns_in_order() -> None:
    assert header_columns(LINES[1].split()) == [
        "quantity",
        "gross",
        "discount",
        "taxable",
        "tax",
        "tax",
        "amount",
    ]
    # Two-word headers are one column.
    assert header_columns("Item Qty Unit Price Taxable Value Amount".split()) == [
        "quantity",
        "unit_price",
        "taxable",
        "amount",
    ]
    assert header_columns("Total items: 1".split()) is None


def test_items_and_the_totals_row_are_read() -> None:
    table = read_text_table(LINES)
    assert table is not None
    assert [(i.description, i.quantity, i.amount) for i in table.items] == [
        ("Wireless earbuds with", Decimal("1.000"), Decimal("3799.00")),
        ("Handling Fee", Decimal("1.000"), Decimal("0.00")),
    ]
    assert (table.subtotal, table.tax, table.total) == (
        Decimal("3219.50"),
        Decimal("579.50"),
        Decimal("3799.00"),
    )


def test_no_header_means_no_table() -> None:
    assert read_text_table(["Cappuccino 2 x 220.00 440.00", "Grand Total 540.00"]) is None
