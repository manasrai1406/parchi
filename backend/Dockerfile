FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

# OpenCV (pulled in by PaddleOCR) needs libGL and GLib; PaddlePaddle needs OpenMP.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so code changes do not reinstall them. The image includes OCR (D-032).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --extra ocr

COPY . .
RUN uv sync --frozen --extra ocr

RUN useradd --create-home parchi && mkdir -p /data/uploads /app/logs && chown -R parchi /data /app/logs
USER parchi

# The OCR models are fetched now, not at run time, so recognition works offline.
RUN python scripts/download_ocr_models.py

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn parchi.api.main:app --host 0.0.0.0 --port 8000"]
