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

RUN useradd --create-home parchi && mkdir -p /data/uploads /app/logs && chown -R parchi /data /app/logs

WORKDIR /app

# Layers run from least to most often changed, so a rebuild redoes as little as possible.
# 1. Dependencies (the image includes OCR, D-032). The cache mount keeps downloaded
#    wheels between builds, so changing one dependency does not download PaddlePaddle again.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra ocr

# 2. OCR models, fetched now so recognition works offline. Only the OCR settings and the
#    download script are copied, so code changes elsewhere do not download them again.
COPY scripts/download_ocr_models.py /opt/ocr-setup/
COPY src/parchi/__init__.py /opt/ocr-setup/parchi/
COPY src/parchi/extraction/__init__.py src/parchi/extraction/ocr.py /opt/ocr-setup/parchi/extraction/
USER parchi
RUN PYTHONPATH=/opt/ocr-setup python /opt/ocr-setup/download_ocr_models.py
USER root

# 3. The app itself.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra ocr

USER parchi

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn parchi.api.main:app --host 0.0.0.0 --port 8000"]
