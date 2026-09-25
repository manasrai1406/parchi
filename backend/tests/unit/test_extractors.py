"""Every synthetic sample through the detector and its extractor (no database)."""

from pathlib import Path

import pytest
from tests.fixtures.synthetic import Sample, all_samples

from parchi.db.enums import FileKind
from parchi.extraction.base import UnreadableFileError
from parchi.extraction.grid import read_receipt
from parchi.extraction.labels import match_label
from parchi.extraction.router import MIN_CONFIDENCE, extractor_for
from parchi.extraction.spreadsheet import pick_delimiter
from parchi.ingestion.detector import detect
from parchi.validation.required import basic_problems

SAMPLES = all_samples()


def write(tmp_path: Path, sample: Sample) -> Path:
    path = tmp_path / sample.name
    path.write_bytes(sample.data)
    return path


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.name)
def test_detector_reads_the_bytes(tmp_path: Path, sample: Sample) -> None:
    path = write(tmp_path, sample)
    if sample.kind == "unreadable":
        with pytest.raises(UnreadableFileError):
            detect(path)
    else:
        assert detect(path).kind.value == sample.kind


def test_detector_ignores_the_file_name(tmp_path: Path) -> None:
    pdf = next(s for s in SAMPLES if s.name == "tax_invoice.pdf")
    renamed = tmp_path / "looks_like_a_sheet.xlsx"
    renamed.write_bytes(pdf.data)
    assert detect(renamed).kind == FileKind.PDF_TEXT


@pytest.mark.parametrize(
    ("data", "reason"),
    [(b"", "empty"), (b"PK\x03\x04not really a zip", "damaged"), (b"\x00\x01\x02binary", "type")],
)
def test_detector_refuses_what_it_cannot_open(tmp_path: Path, data: bytes, reason: str) -> None:
    path = tmp_path / "file"
    path.write_bytes(data)
    with pytest.raises(UnreadableFileError, match=reason):
        detect(path)


READABLE = [s for s in SAMPLES if s.kind in {"excel", "csv", "pdf_text"}]


@pytest.mark.parametrize("sample", READABLE, ids=lambda s: s.name)
def test_extractors_find_the_right_answers(tmp_path: Path, sample: Sample) -> None:
    path = write(tmp_path, sample)
    kind = FileKind(sample.kind)
    extractor = extractor_for(kind)
    assert extractor is not None

    receipts = extractor.extract(path)
    problems = basic_problems(receipts, MIN_CONFIDENCE[kind])

    assert ("parsed" if not problems else "needs_review") == sample.status, problems
    if sample.status != "parsed":
        return
    assert len(receipts) == len(sample.receipts)
    for got, want in zip(receipts, sample.receipts, strict=True):
        assert got.vendor == want.vendor
        assert got.receipt_number == want.receipt_number
        assert got.receipt_date == want.receipt_date
        assert got.total == want.total
        assert got.subtotal == want.subtotal
        assert got.tax == want.tax
        assert len(got.line_items) == want.items


def test_two_page_invoice_is_one_receipt_across_both_pages(tmp_path: Path) -> None:
    sample = next(s for s in SAMPLES if s.name == "two_page_invoice.pdf")
    (receipt,) = extractor_for(FileKind.PDF_TEXT).extract(write(tmp_path, sample))  # type: ignore[union-attr]
    assert receipt.source == "pages 1-2"


def test_scans_and_images_have_no_library_extractor_yet() -> None:
    assert extractor_for(FileKind.PDF_SCAN) is None
    assert extractor_for(FileKind.IMAGE) is None


def test_the_longest_label_wins() -> None:
    assert match_label("Total GST").field == "tax"  # type: ignore[union-attr]
    assert match_label("Grand Total:").field == "total"  # type: ignore[union-attr]
    assert match_label("GSTIN: 27ABCDE1234F1Z5") is None
    assert match_label("Bill No. : 42").rest == "42"  # type: ignore[union-attr]


def test_a_label_next_to_another_label_has_no_value() -> None:
    grid = [["Vendor", "Date"], [None, None], ["Total", 100]]
    receipt = read_receipt(grid, source="test")
    assert receipt is not None
    assert receipt.vendor != "Date"


@pytest.mark.parametrize(
    ("sample", "delimiter"),
    [
        ("Bill No;SB-1\nItem;Amount\nPens;6,000.00", ";"),
        ("Receipt No,FS-1\nDiesel,1167.08", ","),
        ("Item\tAmount\nTea\t20", "\t"),
    ],
)
def test_csv_delimiters_ignore_thousands_commas(sample: str, delimiter: str) -> None:
    assert pick_delimiter(sample) == delimiter
