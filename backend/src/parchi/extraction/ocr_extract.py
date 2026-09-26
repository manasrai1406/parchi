"""Photos and scanned PDFs: clean up, recognise text, then read it like a text PDF (D-032).

Only imported when PaddleOCR is installed (the `ocr` extra).
"""

from pathlib import Path
from typing import Any

import cv2
import pypdfium2 as pdfium

from parchi.db.enums import FileKind, RunParser
from parchi.extraction import ocr
from parchi.extraction.base import UnreadableFileError, UnsupportedFormatError
from parchi.extraction.ocr_layout import mean_score, words_to_lines
from parchi.extraction.pdf_text import Page, group_pages, read_group
from parchi.extraction.preprocess import load_image, prepare
from parchi.schemas.receipt import ReceiptSchema

# Scanned pages are rendered at this resolution for OCR.
RENDER_DPI = 200
MAX_PAGES = 20
HEIC_MESSAGE = (
    "HEIC photos can't be read yet. Please convert the photo to JPG or PNG and upload it again."
)


def _ocr_page(number: int, image: Any) -> tuple[Page, float, int]:
    words = ocr.recognise(prepare(image))
    text = "\n".join(words_to_lines(words))
    return Page(number=number, text=text, tables=[]), mean_score(words), len(words)


def _read_pages(pages: list[tuple[Page, float, int]]) -> list[ReceiptSchema]:
    """Group pages into receipts, then scale each receipt's confidence by how sure the
    OCR was about its pages, so a poor read goes to needs_review (D-032 item 6)."""
    scores = {page.number: (score, count) for page, score, count in pages}
    receipts = []
    for group in group_pages([page for page, _, _ in pages]):
        receipt = read_group(group)
        if receipt is None:
            continue
        weights = [scores[page.number] for page in group]
        words = sum(count for _, count in weights)
        ocr_score = sum(score * count for score, count in weights) / words if words else 0.0
        receipts.append(
            receipt.model_copy(update={"confidence": round(receipt.confidence * ocr_score, 3)})
        )
    return receipts


def _is_heic(path: Path) -> bool:
    with path.open("rb") as handle:
        header = handle.read(12)
    return header[4:8] == b"ftyp" and header[8:12] in {b"heic", b"heix", b"mif1", b"msf1", b"hevc"}


class ImageExtractor:
    handles = frozenset({FileKind.IMAGE})
    parser = RunParser.IMAGE

    def extract(self, path: Path) -> list[ReceiptSchema]:
        if _is_heic(path):
            raise UnsupportedFormatError(HEIC_MESSAGE)
        page = _ocr_page(1, load_image(path))
        for receipt in _read_pages([page]):
            return [receipt.model_copy(update={"source": "photo"})]
        return []


class PdfScanExtractor:
    handles = frozenset({FileKind.PDF_SCAN})
    parser = RunParser.PDF_SCAN

    def extract(self, path: Path) -> list[ReceiptSchema]:
        try:
            document = pdfium.PdfDocument(str(path))
        except pdfium.PdfiumError as exc:
            raise UnreadableFileError(
                "The PDF cannot be opened. It may be damaged or password-protected."
            ) from exc
        try:
            pages = []
            for index in range(min(len(document), MAX_PAGES)):
                bitmap = document[index].render(scale=RENDER_DPI / 72)
                image = bitmap.to_numpy()
                if image.ndim == 3 and image.shape[2] == 4:
                    image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
                pages.append(_ocr_page(index + 1, image))
        finally:
            document.close()
        return _read_pages(pages)
