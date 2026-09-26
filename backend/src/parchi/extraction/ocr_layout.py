"""Rebuild OCR fragments into lines of text, top to bottom and left to right (D-032 item 6).

OCR returns pieces of text with boxes. A piece whose vertical centre falls within the
height of a line's first piece belongs to that printed line; pieces are joined in reading
order, so the same label and text-table rules as text PDFs can read the result.
"""

import re

from parchi.extraction.ocr import Word


def _height(word: Word) -> float:
    return max(word.bottom - word.top, 1.0)


def _centre(word: Word) -> float:
    return (word.top + word.bottom) / 2


# OCR sometimes drops the space across a wide gap. Put back the ones the rules depend on;
# receipt numbers such as INV0421 are left alone.
_YEAR_THEN_TIME = re.compile(r"((?:19|20)\d{2})(\d{1,2}:\d{2})")
_CURRENCY_AFTER_WORD = re.compile(r"(?<=[a-z])(INR|Rs\.?)(?=[\s\d.₹]|$)")
_LABEL_THEN_AMOUNT = re.compile(
    r"\b(total|amount|payable|subtotal|tax|gst|cgst|sgst|igst|utgst|paid|due)(?=[₹\d])",
    re.IGNORECASE,
)


def tidy(line: str) -> str:
    """'14 Aug 202618:42' -> '14 Aug 2026 18:42'; 'Grand TotalINR 540' -> 'Grand Total INR 540'."""
    line = _YEAR_THEN_TIME.sub(r"\1 \2", line)
    line = _CURRENCY_AFTER_WORD.sub(r" \1", line)
    return _LABEL_THEN_AMOUNT.sub(r"\1 ", line)


def _same_line(anchor: Word, word: Word) -> bool:
    """The word's centre lies within the anchor's height band. Comparing with the line's
    first word (not a running average) stops neighbouring lines being chained together."""
    margin = min(_height(anchor), _height(word)) * 0.25
    return anchor.top + margin <= _centre(word) <= anchor.bottom - margin or (
        word.top + margin <= _centre(anchor) <= word.bottom - margin
    )


def words_to_lines(words: list[Word]) -> list[str]:
    if not words:
        return []
    lines: list[list[Word]] = []
    for word in sorted(words, key=_centre):
        line = next((line for line in reversed(lines[-3:]) if _same_line(line[0], word)), None)
        if line is None:
            lines.append([word])
        else:
            line.append(word)
    return [
        tidy(" ".join(word.text for word in sorted(line, key=lambda w: w.left))) for line in lines
    ]


def mean_score(words: list[Word]) -> float:
    """OCR confidence, weighted by how much text each piece holds."""
    total = sum(len(word.text) for word in words)
    if total == 0:
        return 0.0
    return sum(word.score * len(word.text) for word in words) / total
