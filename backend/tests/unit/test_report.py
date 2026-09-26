import io
from datetime import UTC, date, datetime
from decimal import Decimal

import pdfplumber

from parchi.db.enums import FileStatus, FlagSeverity, FlagType, RunParser
from parchi.review.report import build_report
from parchi.schemas.api import FileDetail, FlagOut, RunOut
from parchi.schemas.receipt import ReceiptSchema

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)


def detail() -> FileDetail:
    return FileDetail(
        id=7,
        ref_no="REF-2026-000007",
        original_name="bill <draft> & co.pdf",
        size_bytes=1000,
        kind=None,
        status=FileStatus.PARSED,
        error=None,
        uploaded_at=NOW,
        duplicate_of=None,
        open_flags=1,
        receipts=[],
        flags=[
            FlagOut(
                id=1,
                type=FlagType.ARITHMETIC_MISMATCH,
                severity=FlagSeverity.WARNING,
                detail="Line items add up to ₹900.00, which does not match the total ₹1,180.00.",
                receipt_id=None,
                resolved=False,
                resolved_by=None,
                resolved_at=None,
                created_at=NOW,
            )
        ],
        runs=[
            RunOut(
                id=42,
                parser=RunParser.PDF_TEXT,
                provider=None,
                model=None,
                confidence=0.85,
                duration_ms=120,
                accepted=True,
                error=None,
                ai_approved_by=None,
                ai_approved_at=None,
                finished_at=NOW,
                created_at=NOW,
                result=[
                    ReceiptSchema(
                        vendor="Sharma Traders",
                        receipt_date=date(2026, 8, 14),
                        total=Decimal("1180.00"),
                        confidence=0.85,
                        source="page 1",
                    )
                ],
            )
        ],
    )


def text_of(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        return "\n".join(page.extract_text() or "" for page in document.pages)


def test_report_is_a_pdf_with_the_problems_and_runs() -> None:
    pdf = build_report([detail()])
    assert pdf.startswith(b"%PDF")
    text = text_of(pdf)
    assert "REF-2026-000007" in text
    assert "bill <draft> & co.pdf" in text  # escaped safely, printed as-is
    assert "Rs. 900.00" in text and "₹" not in text
    assert "Run 42" in text and "run_id 42" in text


def test_combined_report_puts_each_file_on_its_own_page() -> None:
    pdf = build_report([detail(), detail()])
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        assert len(document.pages) == 2


def test_empty_report_says_so() -> None:
    assert "No files need attention" in text_of(build_report([]))
