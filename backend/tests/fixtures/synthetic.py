"""Synthetic receipts in varied formats, with the answers a reader should find (D-020).

Used by the tests, and written to data/samples/synthetic/ by scripts/make_samples.py.
They are stand-ins until real samples arrive: Indian GST invoices, retail and fuel
receipts, Rs./INR/rupee-symbol amounts, Indian digit grouping, several date styles.
"""

import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from openpyxl import Workbook

# --- a tiny PDF writer (standard Helvetica, WinAnsi text, ruled lines) ---------------

PAGE_WIDTH, PAGE_HEIGHT = 595, 842

Text = tuple[str, float, float, str, float]  # ("text", x, y, string, size)
Line = tuple[str, float, float, float, float]  # ("line", x1, y1, x2, y2)


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _content(ops: list) -> bytes:
    out = []
    for op in ops:
        if op[0] == "text":
            _, x, y, text, size = op
            out.append(b"BT /F1 %d Tf %.1f %.1f Td (" % (size, x, y) + _escape(text) + b") Tj ET")
        else:
            _, x1, y1, x2, y2 = op
            out.append(b"%.1f %.1f m %.1f %.1f l S" % (x1, y1, x2, y2))
    return b"\n".join(out)


def build_pdf(pages: list[list]) -> bytes:
    """A valid PDF with one content stream per page."""
    objects: list[bytes] = []
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    objects.append(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(pages)))
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    for index, ops in enumerate(pages):
        content_id = page_ids[index] + 1
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
            % (PAGE_WIDTH, PAGE_HEIGHT, content_id)
        )
        stream = _content(ops)
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    )
    return out.getvalue()


class PageBuilder:
    """Write lines top-down, and draw ruled tables pdfplumber can find."""

    def __init__(self, top: float = 790, left: float = 50) -> None:
        self.ops: list = []
        self.y = top
        self.left = left

    def line(self, text: str, size: float = 10, x: float | None = None, gap: float = 16) -> None:
        self.ops.append(("text", x if x is not None else self.left, self.y, text, size))
        self.y -= gap

    def spacer(self, height: float = 10) -> None:
        self.y -= height

    def table(self, rows: list[list[str]], widths: list[float], row_height: float = 20) -> None:
        xs = [self.left]
        for width in widths:
            xs.append(xs[-1] + width)
        top = self.y
        for index, row in enumerate(rows):
            y_top = top - index * row_height
            for col, cell in enumerate(row):
                self.ops.append(("text", xs[col] + 4, y_top - 14, cell, 9))
        bottom = top - len(rows) * row_height
        for index in range(len(rows) + 1):
            y = top - index * row_height
            self.ops.append(("line", xs[0], y, xs[-1], y))
        for x in xs:
            self.ops.append(("line", x, top, x, bottom))
        self.y = bottom - 18


# --- samples -----------------------------------------------------------------------


@dataclass(frozen=True)
class Expected:
    vendor: str
    total: Decimal
    receipt_date: date
    receipt_number: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    items: int = 0


@dataclass(frozen=True)
class Sample:
    name: str
    data: bytes
    kind: str  # the kind the detector should report, or "unreadable"
    status: str  # the status the pipeline should reach
    receipts: list[Expected] = field(default_factory=list)
    note: str = ""


def D(value: str) -> Decimal:
    return Decimal(value)


def _xlsx(fill) -> bytes:
    workbook = Workbook()
    fill(workbook)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _rows(sheet, rows: list[list]) -> None:
    for row in rows:
        sheet.append(row)


def gst_tax_invoice_xlsx() -> Sample:
    def fill(wb: Workbook) -> None:
        ws = wb.active
        ws.title = "Invoice"
        _rows(
            ws,
            [
                ["TAX INVOICE"],
                ["Sharma Traders"],
                ["GSTIN: 27ABCDE1234F1Z5"],
                ["Shop 12, MG Road, Pune 411001"],
                [],
                ["Invoice No:", "ST/2026/0421", None, "Invoice Date:", datetime(2026, 8, 14)],
                [],
                ["Sl", "Description", "Qty", "Rate", "Amount"],
                [1, "A4 paper ream", 4, 250, 1000.0],
                [2, "Stapler", 2, 150, 300.0],
                [3, "Box file", 5, 60, 300.0],
                [],
                [None, None, None, "Sub Total", 1600.0],
                [None, None, None, "CGST @ 9%", 144.0],
                [None, None, None, "SGST @ 9%", 144.0],
                [None, None, None, "Grand Total", 1888.0],
            ],
        )

    return Sample(
        "gst_tax_invoice.xlsx",
        _xlsx(fill),
        "excel",
        "parsed",
        [
            Expected(
                "Sharma Traders",
                D("1888.00"),
                date(2026, 8, 14),
                "ST/2026/0421",
                D("1600.00"),
                D("288.00"),
                3,
            )
        ],
        "GST tax invoice; vendor without a label; real date cell; CGST+SGST lines",
    )


def hotel_bill_xlsx() -> Sample:
    def fill(wb: Workbook) -> None:
        ws = wb.active
        ws.title = "Bill"
        _rows(
            ws,
            [
                ["Vendor: Hotel Surya Palace"],
                ["Bill No: HB-7781", None, "Date: 03/09/2026"],
                [],
                ["Particulars", "Amount"],
                ["Room (2 nights)", "₹ 4,000.00"],
                ["Breakfast", "₹ 500.00"],
                [],
                ["Taxable Value", "₹ 4,500.00"],
                ["GST Amount", "₹ 540.00"],
                ["Total Amount", "₹ 5,040.00"],
            ],
        )

    return Sample(
        "hotel_bill.xlsx",
        _xlsx(fill),
        "excel",
        "parsed",
        [
            Expected(
                "Hotel Surya Palace",
                D("5040.00"),
                date(2026, 9, 3),
                "HB-7781",
                D("4500.00"),
                D("540.00"),
                2,
            )
        ],
        "label and value in one cell; amounts typed as rupee text; dd/mm date text",
    )


def march_bills_xlsx() -> Sample:
    bills = [
        ("Green Leaf Restaurant", "GL-3301", "2026-03-05", "1,250.00"),
        ("City Cabs", "CC-88", "2026-03-11", "640.00"),
        ("Metro Medicals", "MM/2026/77", "2026-03-19", "385.50"),
    ]

    def fill(wb: Workbook) -> None:
        wb.remove(wb.active)
        for vendor, number, day, total in bills:
            ws = wb.create_sheet(vendor.split()[0])
            _rows(
                ws,
                [
                    ["Vendor", "Bill No", "Date"],
                    [vendor, number, day],
                    [],
                    ["Item", "Amount"],
                    ["Services", total],
                    [],
                    ["Total", total],
                ],
            )
        notes = wb.create_sheet("Notes")
        _rows(notes, [["Collected by Priya for March reimbursement."]])

    return Sample(
        "march_bills.xlsx",
        _xlsx(fill),
        "excel",
        "parsed",
        [
            Expected(v, D(t.replace(",", "")), date.fromisoformat(d), n, items=1)
            for v, n, d, t in bills
        ],
        "one receipt per sheet; values below their labels; ISO dates; a notes sheet skipped",
    )


def incomplete_bill_xlsx() -> Sample:
    def fill(wb: Workbook) -> None:
        _rows(
            wb.active,
            [
                ["Supplier: Raju Hardware"],
                ["Bill No: 5512"],
                ["Description", "Amount"],
                ["Paint brush", 120.0],
                ["Nails (1 kg)", 90.0],
            ],
        )

    return Sample(
        "incomplete_bill.xlsx",
        _xlsx(fill),
        "excel",
        "needs_review",
        note="no date and no total: a person must decide",
    )


def expense_log_xlsx() -> Sample:
    def fill(wb: Workbook) -> None:
        _rows(
            wb.active,
            [
                ["Date", "Vendor", "Bill No", "Amount"],
                [datetime(2026, 8, 1), "Chai Point", "A1", 120.0],
                [datetime(2026, 8, 2), "Uber", "A2", 340.0],
            ],
        )

    return Sample(
        "expense_log.xlsx",
        _xlsx(fill),
        "excel",
        "needs_review",
        note="one row per receipt is not read in this phase (D-021)",
    )


def fuel_receipt_csv() -> Sample:
    text = "\n".join(
        [
            "Indian Oil - Sai Fuels",
            "Receipt No,FS-99812",
            "Date,14-Aug-2026",
            "",
            "Description,Qty,Rate,Amount",
            "Diesel,12.35 L,94.50,1167.08",
            "",
            "Total,₹ 1167.08",
        ]
    )
    return Sample(
        "fuel_receipt.csv",
        text.encode("utf-8"),
        "csv",
        "parsed",
        [Expected("Indian Oil - Sai Fuels", D("1167.08"), date(2026, 8, 14), "FS-99812", items=1)],
        "comma CSV, UTF-8, rupee symbol, month-name date, litres as quantity",
    )


def stationery_bill_csv() -> Sample:
    text = "\r\n".join(
        [
            "Supplier Name;Modern Stationers",
            "Bill No.;SB-2026-117",
            "Bill Date;05.09.2026",
            "",
            "Item;Qty;Price;Amount",
            "Registers;50;120.00;6,000.00",
            "Pens (box);30;150.00;4,500.00",
            "",
            "Taxable Amount;10,500.00",
            "IGST;1,890.00",
            "Net Payable;Rs. 12,390.00",
        ]
    )
    return Sample(
        "stationery_bill.csv",
        text.encode("cp1252"),
        "csv",
        "parsed",
        [
            Expected(
                "Modern Stationers",
                D("12390.00"),
                date(2026, 9, 5),
                "SB-2026-117",
                D("10500.00"),
                D("1890.00"),
                2,
            )
        ],
        "semicolon CSV, Windows encoding, dotted date, IGST, Rs. amounts",
    )


def contacts_csv() -> Sample:
    text = "Name,Phone,City\nAsha,98xxxxxx01,Pune\nRavi,98xxxxxx02,Delhi\n"
    return Sample(
        "not_a_receipt.csv",
        text.encode(),
        "csv",
        "needs_review",
        note="a CSV that is not a receipt",
    )


def tax_invoice_pdf() -> Sample:
    page = PageBuilder()
    page.line("TAX INVOICE", size=14, gap=22)
    page.line("Kumar Electronics Pvt Ltd", size=12)
    page.line("GSTIN: 29AAACK1234Q1ZP")
    page.line("45 Residency Road, Bengaluru 560025", gap=24)
    page.line("Invoice No: KE/2026/1187        Date: 22/08/2026", gap=26)
    page.table(
        [
            ["Description", "Qty", "Rate", "Amount"],
            ["HDMI cable 2m", "2", "450.00", "900.00"],
            ["USB-C charger", "1", "1,600.00", "1,600.00"],
        ],
        [250, 50, 90, 100],
    )
    page.line("Sub Total                2,500.00", x=300)
    page.line("CGST @ 9%                  225.00", x=300)
    page.line("SGST @ 9%                  225.00", x=300)
    page.line("Grand Total        Rs. 2,950.00", x=300)
    return Sample(
        "tax_invoice.pdf",
        build_pdf([page.ops]),
        "pdf_text",
        "parsed",
        [
            Expected(
                "Kumar Electronics Pvt Ltd",
                D("2950.00"),
                date(2026, 8, 22),
                "KE/2026/1187",
                D("2500.00"),
                D("450.00"),
                2,
            )
        ],
        "one-page GST invoice, ruled items table, number and date on one line",
    )


def cafe_receipt_pdf() -> Sample:
    page = PageBuilder(left=60)
    page.line("Blue Tokai Coffee Roasters", size=12)
    page.line("Khan Market, New Delhi")
    page.line("Bill # 0045123")
    page.line("14 Aug 2026  18:42", gap=22)
    page.line("Cappuccino   2 x 220.00     440.00")
    page.line("Croissant    1 x 100.00     100.00", gap=22)
    page.line("Grand Total  INR 540.00")
    page.line("Thank you! Visit again.")
    return Sample(
        "cafe_receipt.pdf",
        build_pdf([page.ops]),
        "pdf_text",
        "parsed",
        [Expected("Blue Tokai Coffee Roasters", D("540.00"), date(2026, 8, 14), "0045123")],
        "retail receipt without a table; unlabelled date; INR",
    )


def two_page_invoice_pdf() -> Sample:
    first = PageBuilder()
    first.line("INVOICE", size=14, gap=22)
    first.line("Apex Logistics", size=12)
    first.line("Invoice Number: AL-5521")
    first.line("Invoice Date: 2026-09-01", gap=24)
    rows = [["Description", "Amount"]] + [[f"Shipment {n}", "1,000.00"] for n in range(1, 11)]
    first.table(rows, [300, 120])
    first.line("Continued on next page", size=8)
    second = PageBuilder()
    second.line("Apex Logistics - page 2", size=8, gap=22)
    second.table(
        [["Description", "Amount"]] + [[f"Shipment {n}", "1,000.00"] for n in range(11, 17)],
        [300, 120],
    )
    second.line("Sub Total          16,000.00", x=300)
    second.line("IGST @ 15%          2,400.00", x=300)
    second.line("Total Amount Payable   Rs. 18,400.00", x=300)
    return Sample(
        "two_page_invoice.pdf",
        build_pdf([first.ops, second.ops]),
        "pdf_text",
        "parsed",
        [
            Expected(
                "Apex Logistics",
                D("18400.00"),
                date(2026, 9, 1),
                "AL-5521",
                D("16000.00"),
                D("2400.00"),
                16,
            )
        ],
        "items table continues on page 2, which has no header: one receipt",
    )


def three_bills_pdf() -> Sample:
    bills = [
        ("Annapurna Tiffin Centre", "R-101", "01/09/2026", "450.00"),
        ("Annapurna Tiffin Centre", "R-102", "02/09/2026", "380.00"),
        ("Annapurna Tiffin Centre", "R-103", "03/09/2026", "515.00"),
    ]
    pages = []
    for vendor, number, day, total in bills:
        page = PageBuilder()
        page.line("CASH MEMO", size=13, gap=20)
        page.line(vendor, size=12)
        page.line(f"Receipt No: {number}")
        page.line(f"Dated: {day}", gap=22)
        page.line("Lunch thali and snacks")
        page.line(f"Net Amount   {total}")
        pages.append(page.ops)
    return Sample(
        "three_bills.pdf",
        build_pdf(pages),
        "pdf_text",
        "parsed",
        [Expected(v, D(t), date(int(d[6:]), int(d[3:5]), int(d[:2])), n) for v, n, d, t in bills],
        "three bills scanned into one PDF, one per page",
    )


def fuel_bill_pdf() -> Sample:
    page = PageBuilder()
    page.line("HP Petrol Pump - Highway Fuels", size=12)
    page.line("NH48, Km 212, Gurugram")
    page.line("Txn No: 889201")
    page.line("Date: 14.08.26   Time: 09:15", gap=22)
    page.line("Product: Petrol    Volume: 19.80 L    Rate: 101.01")
    page.line("Amount Payable   Rs. 2,000.00")
    return Sample(
        "fuel_bill.pdf",
        build_pdf([page.ops]),
        "pdf_text",
        "parsed",
        [Expected("HP Petrol Pump - Highway Fuels", D("2000.00"), date(2026, 8, 14), "889201")],
        "fuel slip: two-digit year, dotted date, 'Amount Payable'",
    )


def scanned_pdf() -> Sample:
    page = PageBuilder()
    page.ops.append(("line", 50, 700, 545, 700))
    page.ops.append(("line", 50, 300, 545, 300))
    return Sample(
        "scanned_receipt.pdf",
        build_pdf([page.ops]),
        "pdf_scan",
        "needs_review",
        note="no text layer: waits for OCR (phase 5)",
    )


def damaged_pdf() -> Sample:
    return Sample(
        "damaged.pdf",
        b"%PDF-1.4\n1 0 obj << /Type /Catalog >> garbage without xref",
        "unreadable",
        "flagged",
        note="corrupt bytes: flagged unreadable, never retried",
    )


def all_samples() -> list[Sample]:
    return [
        gst_tax_invoice_xlsx(),
        hotel_bill_xlsx(),
        march_bills_xlsx(),
        incomplete_bill_xlsx(),
        expense_log_xlsx(),
        fuel_receipt_csv(),
        stationery_bill_csv(),
        contacts_csv(),
        tax_invoice_pdf(),
        cafe_receipt_pdf(),
        two_page_invoice_pdf(),
        three_bills_pdf(),
        fuel_bill_pdf(),
        scanned_pdf(),
        damaged_pdf(),
    ]
