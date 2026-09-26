"""Clean up a photo or scanned page before OCR (plan phase 5), with OpenCV.

Phone photos arrive sideways, skewed, shadowed or faded. This fixes what OCR is worst
at: EXIF rotation (applied when the image is opened), small skew angles, uneven
lighting, and images far too small or too large. Large rotations (90/180/270 degrees)
are left to PaddleOCR's page orientation model.
"""

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from parchi.extraction.base import UnreadableFileError

MAX_SIDE = 2400  # larger photos are scaled down: slower, not more accurate
MIN_SIDE = 900  # tiny images are scaled up so small print survives
MAX_DESKEW_DEGREES = 20.0  # beyond this, it is a rotation, not a skew
MIN_DESKEW_DEGREES = 0.5


def load_image(path: Path) -> Any:
    """A BGR image. OpenCV applies the EXIF orientation of phone photos."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise UnreadableFileError("The image cannot be opened. It may be damaged.")
    return image


def resize(image: Any) -> Any:
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    if longest < MIN_SIDE:
        scale = MIN_SIDE / longest
        return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return image


def _rotate(image: Any, degrees: float, border: int) -> Any:
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
    return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=border)


def _sharpness(ink: Any, degrees: float) -> float:
    """How crisply rows of text line up after turning by `degrees`: straight lines of
    text give strongly alternating row sums (ink rows, gap rows)."""
    rows = _rotate(ink, degrees, cv2.BORDER_CONSTANT).sum(axis=1, dtype=np.float64)
    return float(np.square(np.diff(rows)).sum())


def skew_angle(image: Any) -> float:
    """The turn (degrees, counter-clockwise) that straightens the text, found by the
    projection-profile method; 0 if the text is already straight."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, 1000 / max(gray.shape))
    if scale < 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    # Local thresholding picks out text strokes; a dark table around the paper, or a
    # shadow, changes slowly, so it is not mistaken for ink.
    ink = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15
    )
    if cv2.countNonZero(ink) < 200:
        return 0.0
    coarse = max(
        np.arange(-MAX_DESKEW_DEGREES, MAX_DESKEW_DEGREES + 0.01, 1.0),
        key=lambda angle: _sharpness(ink, float(angle)),
    )
    fine = max(
        np.arange(coarse - 1.0, coarse + 1.01, 0.1),
        key=lambda angle: _sharpness(ink, float(angle)),
    )
    return round(float(fine), 1)


def deskew(image: Any) -> Any:
    angle = skew_angle(image)
    if abs(angle) < MIN_DESKEW_DEGREES:
        return image
    return _rotate(image, angle, cv2.BORDER_REPLICATE)


def even_lighting(image: Any) -> Any:
    """Remove shadows and fading: divide each channel by its blurred background."""
    planes = []
    for plane in cv2.split(image):
        background = cv2.medianBlur(cv2.dilate(plane, np.ones((7, 7), np.uint8)), 21)
        flattened = 255 - cv2.absdiff(plane, background)
        planes.append(cv2.normalize(flattened, None, 0, 255, cv2.NORM_MINMAX))
    return cv2.merge(planes)


def prepare(image: Any) -> Any:
    return even_lighting(deskew(resize(image)))
