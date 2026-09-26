"""Synthetic receipt photos and scans, damaged like real ones (D-033).

The text-PDF samples are rendered to images (pypdfium2) and then photographed badly:
rotated, skewed, shadowed, faded, blurred, noisy, compressed. Needs OpenCV (Docker).
"""

import io
from collections.abc import Callable

import cv2
import numpy as np
import pypdfium2 as pdfium

from tests.fixtures.synthetic import (
    Sample,
    cafe_receipt_pdf,
    fuel_bill_pdf,
    marketplace_invoices_pdf,
    tax_invoice_pdf,
    three_bills_pdf,
)

RENDER_DPI = 150
rng = np.random.default_rng(seed=7)  # the same damage every run


def render_pages(pdf: bytes, dpi: int = RENDER_DPI) -> list[np.ndarray]:
    document = pdfium.PdfDocument(pdf)
    pages = []
    for page in document:
        image = page.render(scale=dpi / 72).to_numpy()
        if image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        pages.append(np.ascontiguousarray(image))
    document.close()
    return pages


def crop_to_ink(image: np.ndarray, margin: int = 40) -> np.ndarray:
    """Cut the white page down to the receipt, like a photo framing just the paper."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    points = cv2.findNonZero(255 - gray)
    x, y, w, h = cv2.boundingRect(points)
    top, left = max(y - margin, 0), max(x - margin, 0)
    return image[top : y + h + margin, left : x + w + margin].copy()


def on_table(image: np.ndarray, border: int = 60) -> np.ndarray:
    """The receipt lying on a grey-brown table."""
    return cv2.copyMakeBorder(
        image, border, border, border, border, cv2.BORDER_CONSTANT, value=(88, 104, 120)
    )


def rotate(image: np.ndarray, degrees: float) -> np.ndarray:
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w, new_h = int(height * sin + width * cos), int(height * cos + width * sin)
    matrix[0, 2] += new_w / 2 - width / 2
    matrix[1, 2] += new_h / 2 - height / 2
    return cv2.warpAffine(image, matrix, (new_w, new_h), borderValue=(88, 104, 120))


def shadow(image: np.ndarray, strength: float = 0.45) -> np.ndarray:
    """A soft shadow falling across one side, as from a hand or phone."""
    height, width = image.shape[:2]
    ramp = np.linspace(1 - strength, 1.0, width, dtype=np.float32)
    mask = np.tile(ramp, (height, 1))[..., None]
    return (image.astype(np.float32) * mask).clip(0, 255).astype(np.uint8)


def fade(image: np.ndarray, contrast: float = 0.45) -> np.ndarray:
    """Old thermal paper: grey ink on a greyish page."""
    faded = image.astype(np.float32) * contrast + 255 * (1 - contrast) * 0.85
    return faded.clip(0, 255).astype(np.uint8)


def noise(image: np.ndarray, sigma: float = 10.0) -> np.ndarray:
    grain = rng.normal(0, sigma, image.shape).astype(np.float32)
    return (image.astype(np.float32) + grain).clip(0, 255).astype(np.uint8)


def blur(image: np.ndarray, size: int = 3) -> np.ndarray:
    return cv2.GaussianBlur(image, (size, size), 0)


def encode(image: np.ndarray, ext: str, quality: int = 85) -> bytes:
    params = {
        ".jpg": [cv2.IMWRITE_JPEG_QUALITY, quality],
        ".webp": [cv2.IMWRITE_WEBP_QUALITY, quality],
        ".png": [],
    }[ext]
    ok, data = cv2.imencode(ext, image, params)
    if not ok:
        raise RuntimeError(f"could not encode {ext}")
    return data.tobytes()


def scanned_pdf(pages: list[np.ndarray]) -> bytes:
    """A PDF whose pages are only pictures (JPEG), like an office scanner makes."""
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    page_ids = [3 + 3 * i for i in range(len(pages))]
    kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
    objects.append(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(pages)))
    for index, image in enumerate(pages):
        jpeg = encode(image, ".jpg", 80)
        height, width = image.shape[:2]
        pw, ph = width * 72 / RENDER_DPI, height * 72 / RENDER_DPI
        page_id = page_ids[index]
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.1f %.1f] "
            b"/Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
            % (pw, ph, page_id + 1, page_id + 2)
        )
        objects.append(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
            b"/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n"
            % (width, height, len(jpeg))
            + jpeg
            + b"\nendstream"
        )
        draw = b"q %.1f 0 0 %.1f 0 0 cm /Im0 Do Q" % (pw, ph)
        objects.append(b"<< /Length %d >>\nstream\n" % len(draw) + draw + b"\nendstream")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    )
    return out.getvalue()


def _photo(
    source: Sample,
    name: str,
    damage: Callable[[np.ndarray], np.ndarray],
    ext: str,
    status: str = "parsed",
    note: str = "",
) -> Sample:
    (page,) = render_pages(source.data)[:1]
    image = damage(crop_to_ink(page))
    return Sample(name, encode(image, ext), "image", status, source.receipts[:1], note)


def all_image_samples() -> list[Sample]:
    cafe, fuel, invoice = cafe_receipt_pdf(), fuel_bill_pdf(), tax_invoice_pdf()
    three, marketplace = three_bills_pdf(), marketplace_invoices_pdf()
    samples = [
        _photo(cafe, "cafe_photo.jpg", lambda i: on_table(i), ".jpg", note="a clean photo"),
        _photo(
            fuel,
            "fuel_photo_skewed.jpg",
            lambda i: noise(rotate(on_table(i), 6)),
            ".jpg",
            note="taken at an angle (6 degrees), grainy",
        ),
        _photo(
            invoice,
            "tax_invoice_shadow.png",
            lambda i: blur(shadow(i)),
            ".png",
            note="a shadow across the page, slightly soft",
        ),
        _photo(
            cafe,
            "cafe_faded.webp",
            lambda i: fade(i),
            ".webp",
            note="faded thermal paper, low contrast",
        ),
        _photo(
            fuel,
            "fuel_upside_down.jpg",
            lambda i: rotate(on_table(i), 180),
            ".jpg",
            note="photographed upside down",
        ),
        _photo(
            fuel,
            "fuel_sideways.jpg",
            lambda i: rotate(on_table(i), 90),
            ".jpg",
            note="photographed sideways",
        ),
        _photo(
            cafe,
            "cafe_unreadable.jpg",
            lambda i: noise(blur(i, 21), 40),
            ".jpg",
            status="needs_review",
            note="too blurred to read: must go to needs_review, not guess",
        ),
    ]
    scans = [noise(crop_to_ink(page, 60), 6) for page in render_pages(three.data)]
    samples.append(
        Sample(
            "three_bills_scan.pdf",
            scanned_pdf(scans),
            "pdf_scan",
            "parsed",
            three.receipts,
            "three bills scanned into one image-only PDF",
        )
    )
    market_scans = [crop_to_ink(page, 60) for page in render_pages(marketplace.data, 200)]
    samples.append(
        Sample(
            "marketplace_scan.pdf",
            scanned_pdf(market_scans),
            "pdf_scan",
            "parsed",
            marketplace.receipts,
            "two invoices with text items tables, scanned",
        )
    )
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + bytes(64)
    samples.append(
        Sample("iphone_photo.heic", heic, "image", "needs_review", note="HEIC is not read yet")
    )
    return samples
