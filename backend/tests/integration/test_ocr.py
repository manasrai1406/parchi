"""Photos and scans through PaddleOCR (Phase 5). Runs where the `ocr` extra is installed:
in Docker, `docker compose exec api pytest tests/integration/test_ocr.py`."""

from pathlib import Path

import pytest

from parchi.extraction import ocr

if not ocr.available():
    pytest.skip("PaddleOCR is not installed here (it runs in Docker)", allow_module_level=True)

from tests.fixtures.synthetic import fuel_bill_pdf
from tests.fixtures.synthetic_images import (
    all_image_samples,
    crop_to_ink,
    render_pages,
    rotate,
)

from parchi.db.enums import FileKind
from parchi.extraction.base import UnsupportedFormatError
from parchi.extraction.preprocess import deskew, load_image, skew_angle
from parchi.extraction.router import MIN_CONFIDENCE, extractor_for
from parchi.ingestion.detector import detect
from parchi.validation.required import basic_problems

SAMPLES = all_image_samples()


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_skew_is_measured_and_removed() -> None:
    page = crop_to_ink(render_pages(fuel_bill_pdf().data)[0])
    tilted = rotate(page, 6)
    assert abs(abs(skew_angle(tilted)) - 6) < 1.5
    assert abs(skew_angle(deskew(tilted))) < 1.0  # straightened to within a degree


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s.name)
def test_photo_and_scan_samples(tmp_path: Path, sample) -> None:
    path = write(tmp_path, sample.name, sample.data)
    detection = detect(path)
    assert detection.kind.value == sample.kind
    extractor = extractor_for(detection.kind)
    assert extractor is not None

    try:
        receipts = extractor.extract(path)
    except UnsupportedFormatError:
        assert sample.status == "needs_review"
        return
    problems = basic_problems(receipts, MIN_CONFIDENCE[FileKind(sample.kind)])
    status = "needs_review" if problems else "parsed"
    assert status == sample.status, (problems, receipts)
    if status == "parsed":
        assert len(receipts) == len(sample.receipts)
        for got, want in zip(receipts, sample.receipts, strict=True):
            assert got.total == want.total
            assert got.receipt_date == want.receipt_date


def test_images_open_with_opencv(tmp_path: Path) -> None:
    sample = next(s for s in SAMPLES if s.name.endswith(".webp"))
    image = load_image(write(tmp_path, sample.name, sample.data))
    assert image.ndim == 3
