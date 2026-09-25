"""The basic checks a library result must pass to be accepted (D-024 item 2).

Phase 4 adds arithmetic, date and duplicate rules. Messages name fields, never values,
so they are safe to log and to show in the file list.
"""

from parchi.schemas.receipt import ReceiptSchema

FIELD_NAMES = {"vendor": "vendor", "receipt_date": "date", "total": "total"}


def basic_problems(receipts: list[ReceiptSchema], min_confidence: float) -> list[str]:
    """Why these receipts cannot be accepted as they are. Empty means they pass."""
    if not receipts:
        return ["No receipt could be found in this file."]
    problems = []
    for index, receipt in enumerate(receipts, start=1):
        which = f"Receipt {index}" if len(receipts) > 1 else "The receipt"
        missing = [FIELD_NAMES[name] for name in receipt.missing_required()]
        if missing:
            problems.append(f"{which} is missing its {_join(missing)}.")
        elif receipt.confidence < min_confidence:
            problems.append(f"{which} was read with low confidence ({receipt.confidence:.0%}).")
    return problems


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def summarize(problems: list[str], limit: int = 3) -> str:
    shown = problems[:limit]
    more = len(problems) - len(shown)
    return " ".join(shown) + (f" And {more} more." if more else "")
