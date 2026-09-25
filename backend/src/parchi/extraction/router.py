"""Pick the library extractor for a file kind (stage 4)."""

from parchi.db.enums import FileKind
from parchi.extraction.base import Extractor
from parchi.extraction.pdf_text import PdfTextExtractor
from parchi.extraction.spreadsheet import CsvExtractor, ExcelExtractor

EXTRACTORS: list[Extractor] = [ExcelExtractor(), CsvExtractor(), PdfTextExtractor()]

# The lowest confidence at which a file type's result is accepted (D-013 item 6, D-024).
MIN_CONFIDENCE: dict[FileKind, float] = {
    FileKind.EXCEL: 0.6,
    FileKind.CSV: 0.6,
    FileKind.PDF_TEXT: 0.6,
    FileKind.PDF_SCAN: 0.7,
    FileKind.IMAGE: 0.7,
}


def extractor_for(kind: FileKind) -> Extractor | None:
    """None for kinds without a library extractor yet (scans and images, phase 5)."""
    return next((extractor for extractor in EXTRACTORS if kind in extractor.handles), None)
