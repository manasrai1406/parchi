"""Download PaddleOCR's models while the Docker image is built, so OCR runs offline (D-032).

Runs the engine once on a blank page with the same options the app uses.
"""

import numpy as np

from parchi.extraction import ocr

if __name__ == "__main__":
    if not ocr.available():
        raise SystemExit("PaddleOCR is not installed (the 'ocr' extra).")
    ocr.recognise(np.full((200, 400, 3), 255, dtype=np.uint8))
    print("OCR models are ready.")
