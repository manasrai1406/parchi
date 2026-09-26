"""Score the readers against samples with known answers (plan: benchmark, D-033).

Usage (from backend/): uv run python scripts/benchmark_extractors.py [--only-images]
In Docker (with OCR):  docker compose exec api python scripts/benchmark_extractors.py

Samples: the synthetic ones (images too when OpenCV is installed), plus any real ones in
data/samples/real/ listed in data/samples/real/answers.json, in the format
scripts/make_samples.py writes. Prints a Markdown report; nothing is stored or sent.
"""

import argparse
import json
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tests.fixtures.synthetic import Expected, Sample, all_samples  # noqa: E402

from parchi.extraction.base import UnreadableFileError, UnsupportedFormatError  # noqa: E402
from parchi.extraction.router import MIN_CONFIDENCE, extractor_for  # noqa: E402
from parchi.ingestion.detector import detect  # noqa: E402
from parchi.validation.required import basic_problems  # noqa: E402

REAL = BACKEND.parent / "data" / "samples" / "real"
FIELDS = ("vendor", "receipt_number", "receipt_date", "subtotal", "tax", "total")


@dataclass
class Score:
    name: str
    kind: str
    expected_status: str
    status: str = "?"
    seconds: float = 0.0
    matched: dict[str, int] = field(default_factory=dict)
    compared: dict[str, int] = field(default_factory=dict)
    note: str = ""


def _same(field_name: str, got: object, want: object) -> bool:
    if field_name == "vendor":
        return " ".join(str(got or "").split()).lower() == " ".join(str(want or "").split()).lower()
    return got == want


def score(sample: Sample, workdir: Path) -> Score:
    result = Score(sample.name, sample.kind, sample.status, note=sample.note)
    path = workdir / sample.name
    path.write_bytes(sample.data)
    started = time.perf_counter()
    try:
        detection = detect(path)
        extractor = extractor_for(detection.kind)
        if extractor is None:
            result.status = "needs_review"
            result.note = "no reader installed here (OCR runs in Docker)"
            return result
        receipts = extractor.extract(path)
        problems = basic_problems(receipts, MIN_CONFIDENCE[detection.kind])
        result.status = "needs_review" if problems else "parsed"
    except UnsupportedFormatError:
        result.status, receipts = "needs_review", []
    except UnreadableFileError:
        result.status, receipts = "flagged", []
    finally:
        result.seconds = time.perf_counter() - started

    for got, want in zip(receipts, sample.receipts, strict=False):
        for name in FIELDS:
            expected = getattr(want, name)
            if expected is None:
                continue
            result.compared[name] = result.compared.get(name, 0) + 1
            result.matched[name] = result.matched.get(name, 0) + _same(
                name, getattr(got, name), expected
            )
    # Receipts that were expected but not found count as misses on every field.
    for want in sample.receipts[len(receipts) :]:
        for name in FIELDS:
            if getattr(want, name) is not None:
                result.compared[name] = result.compared.get(name, 0) + 1
    return result


def real_samples() -> list[Sample]:
    answers_file = REAL / "answers.json"
    if not answers_file.exists():
        return []
    samples = []
    for name, answer in json.loads(answers_file.read_text(encoding="utf-8")).items():
        receipts = [
            Expected(
                vendor=r["vendor"],
                total=Decimal(r["total"]),
                receipt_date=date.fromisoformat(r["receipt_date"]),
                receipt_number=r.get("receipt_number"),
                subtotal=Decimal(r["subtotal"]) if r.get("subtotal") else None,
                tax=Decimal(r["tax"]) if r.get("tax") else None,
                items=r.get("line_items", 0),
            )
            for r in answer.get("receipts", [])
        ]
        samples.append(
            Sample(
                f"real/{name}",
                (REAL / name).read_bytes(),
                answer.get("detected_as", "?"),
                answer.get("expected_status", "parsed"),
                receipts,
                answer.get("note", "real sample"),
            )
        )
    return samples


def synthetic_samples(only_images: bool) -> list[Sample]:
    samples = [] if only_images else all_samples()
    try:
        from tests.fixtures.synthetic_images import all_image_samples
    except ImportError:
        print("(OpenCV is not installed here: photo samples skipped. Run in Docker.)\n")
        return samples
    return samples + all_image_samples()


def report(scores: list[Score]) -> str:
    lines = [
        "| Sample | Type | Expected | Got | Fields right | Seconds |",
        "|---|---|---|---|---|---|",
    ]
    for s in scores:
        right, total = sum(s.matched.values()), sum(s.compared.values())
        ok = "✅" if s.status == s.expected_status else "❌"
        fields = f"{right}/{total}" if total else "—"
        lines.append(
            f"| {s.name} | {s.kind} | {s.expected_status} | {ok} {s.status} | {fields} "
            f"| {s.seconds:.1f} |"
        )
    lines += ["", "| Field | Accuracy |", "|---|---|"]
    for name in FIELDS:
        compared = sum(s.compared.get(name, 0) for s in scores)
        matched = sum(s.matched.get(name, 0) for s in scores)
        if compared:
            lines.append(f"| {name} | {matched}/{compared} ({matched / compared:.0%}) |")
    statuses = sum(s.status == s.expected_status for s in scores)
    lines += ["", f"Status as expected: {statuses}/{len(scores)}"]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only-images", action="store_true", help="photos and scans only")
    args = parser.parse_args()
    samples = synthetic_samples(args.only_images) + real_samples()
    with tempfile.TemporaryDirectory() as workdir:
        scores = [score(sample, Path(workdir)) for sample in samples]
    print(report(scores))


if __name__ == "__main__":
    main()
