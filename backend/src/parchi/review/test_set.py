"""Receipts a person keeps as tests, on this machine only (D-048).

Each kept file is copied to REAL_SAMPLES_DIR with the answer the person confirmed, in
answers.json. scripts/check_real_samples.py reads them back to catch a reader getting
worse. The folder is under data/, which is never committed.
"""

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from parchi.schemas.api import ReceiptIn

ANSWERS = "answers.json"
_lock = threading.Lock()


def _answer(receipt: ReceiptIn) -> dict[str, Any]:
    money = lambda value: None if value is None else f"{value:.2f}"  # noqa: E731
    return {
        "vendor": receipt.vendor,
        "receipt_number": receipt.receipt_number,
        "receipt_date": receipt.receipt_date.isoformat(),
        "subtotal": money(receipt.subtotal),
        "tax": money(receipt.tax),
        "total": money(receipt.total),
    }


def read_answers(directory: Path) -> dict[str, list[dict[str, Any]]]:
    path = directory / ANSWERS
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def keep(
    directory: Path, source: Path, ref_no: str, original_name: str, receipts: list[ReceiptIn]
) -> str:
    """Copy the original and record the confirmed answer. Returns the kept file's name."""
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{ref_no}__{Path(original_name).name}"
    shutil.copyfile(source, directory / name)
    with _lock:
        answers = read_answers(directory)
        answers[name] = [_answer(receipt) for receipt in receipts]
        partial = directory / f".{ANSWERS}.tmp"
        partial.write_text(json.dumps(answers, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(partial, directory / ANSWERS)
    return name
