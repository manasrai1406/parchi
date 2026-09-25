"""Write the synthetic receipts (D-020) and their expected answers to data/samples/synthetic/.

Usage (from backend/): uv run python scripts/make_samples.py
Upload the files on the Upload page to see the pipeline work on them.
"""

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tests.fixtures.synthetic import all_samples  # noqa: E402

TARGET = BACKEND.parent / "data" / "samples" / "synthetic"


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    answers = {}
    for sample in all_samples():
        (TARGET / sample.name).write_bytes(sample.data)
        answers[sample.name] = {
            "detected_as": sample.kind,
            "expected_status": sample.status,
            "note": sample.note,
            "receipts": [
                {
                    "vendor": r.vendor,
                    "receipt_number": r.receipt_number,
                    "receipt_date": r.receipt_date.isoformat(),
                    "subtotal": str(r.subtotal) if r.subtotal is not None else None,
                    "tax": str(r.tax) if r.tax is not None else None,
                    "total": str(r.total),
                    "line_items": r.items,
                }
                for r in sample.receipts
            ],
        }
    (TARGET / "answers.json").write_text(json.dumps(answers, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(answers)} samples and answers.json to {TARGET}")


if __name__ == "__main__":
    main()
