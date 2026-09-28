"""Re-read every receipt kept as a test and compare it with the confirmed answer (D-048).

Usage (the stack running; OCR is in the Docker image):
    docker compose exec api python scripts/check_real_samples.py
    docker compose exec api python scripts/check_real_samples.py --library-only

The kept files and answers live in REAL_SAMPLES_DIR (data/samples/real/), never committed.
Learned labels are used too, as the pipeline would, unless --library-only is given.
Exits with 1 when any field is read wrong, so it can gate a change to the readers.
Prints field names and amounts only for this machine's terminal; nothing is logged.
"""

import argparse
import asyncio
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from parchi.config import get_settings
from parchi.db.session import get_engine, get_sessionmaker
from parchi.extraction.base import UnreadableFileError, UnsupportedFormatError
from parchi.extraction.learned import apply_learned
from parchi.extraction.router import extractor_for
from parchi.ingestion.detector import detect
from parchi.review.test_set import read_answers
from parchi.schemas.receipt import ReceiptSchema

# The vendor is left out: people often tidy the printed name, which is not a misread.
CHECKED = ("receipt_number", "receipt_date", "subtotal", "tax", "total")


def _same(field: str, expected: object, got: object) -> bool:
    if expected is None:
        return True  # nothing confirmed for this field
    if got is None:
        return False
    if field == "receipt_date":
        return date.fromisoformat(str(expected)) == got
    if field == "receipt_number":
        return str(expected).strip().lower() == str(got).strip().lower()
    return Decimal(str(expected)) == Decimal(str(got))


async def read(path: Path, learned: bool) -> list[ReceiptSchema]:
    kind = detect(path).kind
    extractor = extractor_for(kind)
    if extractor is None:
        return []
    receipts = await asyncio.to_thread(extractor.extract, path)
    if learned and receipts:
        async with get_sessionmaker()() as session:
            receipts = await apply_learned(session, receipts)
            await session.rollback()  # checking must not count as using a label
    return receipts


async def check(directory: Path, learned: bool) -> int:
    answers = read_answers(directory)
    if not answers:
        print(f"No kept receipts in {directory}. Tick 'Keep as a test receipt' on the Review page.")
        return 0
    wrong_files = 0
    for name, expected in sorted(answers.items()):
        path = directory / name
        try:
            got = await read(path, learned)
        except (UnreadableFileError, UnsupportedFormatError, OSError) as exc:
            print(f"FAIL {name}: cannot be read ({exc})")
            wrong_files += 1
            continue
        problems = []
        if len(got) != len(expected):
            problems.append(f"{len(got)} receipts read, {len(expected)} expected")
        for index, answer in enumerate(expected[: len(got)]):
            for field in CHECKED:
                value = getattr(got[index], field)
                if not _same(field, answer.get(field), value):
                    problems.append(
                        f"#{index + 1} {field}: expected {answer.get(field)}, read {value}"
                    )
        if problems:
            wrong_files += 1
            print(f"FAIL {name}")
            for problem in problems:
                print(f"     {problem}")
        else:
            print(f"ok   {name}")
    print(f"\n{len(answers) - wrong_files} of {len(answers)} kept receipts read correctly.")
    return 1 if wrong_files else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--library-only", action="store_true", help="ignore learned labels")
    parser.add_argument("--dir", type=Path, help="default: REAL_SAMPLES_DIR")
    args = parser.parse_args()
    directory = args.dir or get_settings().real_samples_dir
    if directory is None:
        raise SystemExit("Set REAL_SAMPLES_DIR or pass --dir.")

    async def run() -> int:
        try:
            return await check(directory, learned=not args.library_only)
        finally:
            await get_engine().dispose()

    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    sys.exit(asyncio.run(run(), loop_factory=loop))


if __name__ == "__main__":
    main()
