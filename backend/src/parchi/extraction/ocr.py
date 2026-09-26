"""Text recognition with PaddleOCR (D-032).

PaddleOCR is an optional extra installed only in the Docker image. Without it,
`available()` is False and scans and photos wait in needs_review. Nothing here sends
an image anywhere: the models are downloaded while the image is built.
"""

import importlib.util
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

# Used for every file, and by scripts/download_ocr_models.py when the image is built.
ENGINE_OPTIONS: dict[str, Any] = {
    # Mobile models: several times less memory than the default "medium" ones, which ran
    # Docker out of memory on an 8 GB laptop (D-034). Receipts are printed English text.
    "text_detection_model_name": "PP-OCRv5_mobile_det",
    "text_recognition_model_name": "en_PP-OCRv5_mobile_rec",
    # Pages photographed sideways or upside down are turned the right way up.
    "use_doc_orientation_classify": True,
    # Flattening curled paper is slow on a CPU and rarely needed for receipts.
    "use_doc_unwarping": False,
    # Per-line orientation is a further model; the page orientation above covers photos.
    "use_textline_orientation": False,
    # PaddlePaddle 3.3's oneDNN acceleration fails on some models ("ConvertPirAttribute2
    # RuntimeAttribute not support"); plain CPU inference is slower but reliable.
    "enable_mkldnn": False,
    "cpu_threads": 2,
}

_lock = threading.Lock()


@dataclass(frozen=True)
class Word:
    """One piece of recognised text and where it sits on the page (pixels)."""

    text: str
    score: float
    left: float
    top: float
    right: float
    bottom: float


def available() -> bool:
    return importlib.util.find_spec("paddleocr") is not None


@lru_cache(maxsize=1)
def _engine() -> Any:
    from paddleocr import PaddleOCR  # imported lazily: heavy, and optional

    return PaddleOCR(**ENGINE_OPTIONS)


def _box(item: Any) -> tuple[float, float, float, float]:
    """A box as (left, top, right, bottom), from [x1, y1, x2, y2] or a polygon of points."""
    data = item.tolist() if hasattr(item, "tolist") else list(item)
    if data and isinstance(data[0], list | tuple):
        xs = [float(point[0]) for point in data]
        ys = [float(point[1]) for point in data]
        return min(xs), min(ys), max(xs), max(ys)
    left, top, right, bottom = (float(value) for value in data[:4])
    return left, top, right, bottom


def recognise(image: Any) -> list[Word]:
    """Every piece of text PaddleOCR finds in a BGR image (a numpy array)."""
    with _lock:  # one engine per process; PaddleOCR is not safe to share across threads
        results = _engine().predict(image)
    words: list[Word] = []
    for result in results:
        texts = result["rec_texts"]
        scores = result["rec_scores"]
        boxes = result.get("rec_boxes")
        if boxes is None or len(boxes) != len(texts):
            boxes = result["rec_polys"]
        for text, score, box in zip(texts, scores, boxes, strict=False):
            text = str(text).strip()
            if text:
                words.append(Word(text, float(score), *_box(box)))
    return words
