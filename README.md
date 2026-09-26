# Parchi

**Receipt ingestion, extraction and review — library-first, with AI only when a person approves it.**

Parchi takes in receipts as PDFs, photos and spreadsheets, extracts them with open-source libraries, validates the results, and stores them in PostgreSQL. A React app lets people upload files, follow their progress, review and fix problems, and query the data. AI extraction (Claude or OpenAI) is strictly opt-in: it never runs unless a person approves it, and every approval is recorded.

> **Status:** early development. Phases 1–5 of 7 are complete (foundation, upload and registration, library extraction, validation and review, OCR). See the [roadmap](#roadmap).

---

## Contents

- [Why Parchi](#why-parchi)
- [Features](#features)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Development](#development)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [API](#api)
- [Roadmap](#roadmap)
- [Documentation](#documentation)
- [License](#license)

## Why Parchi

Businesses handle thousands of receipts a month in every format imaginable. Parchi is built around a few firm principles:

- **Library first.** Extraction always starts with deterministic libraries (pandas, pdfplumber, PyMuPDF, OCR). Files that fail checks wait for a person instead of being sent to an AI automatically.
- **AI only with approval.** No code path calls an LLM without an explicit approval, enforced on the server and backed by a database constraint. AI is disabled by default, capped per day, and every approval is stored with who approved it, when, and which provider.
- **Nothing is lost.** Every extraction attempt is kept as its own record, so a re-run never overwrites an earlier result.
- **Traceable.** Every file gets a reference number (`REF-2026-000412`) that appears in the UI and in every log line. Logs never contain receipt contents or secrets.
- **Money is exact.** Amounts are stored as decimals, never floats. All amounts are in Indian rupees (INR).

## Features

**Available now**

- Drag-and-drop upload with per-file progress
- Files stored by content hash, each assigned a unique reference number
- Duplicate detection: identical files are flagged, and the user decides whether to keep a copy
- File list with status filters, search by name or reference number, pagination and downloads
- File deletion with confirmation, safe for shared copies
- File-type detection from the bytes, not the file name
- Library extraction for Excel (.xlsx, .xls), CSV and digital PDFs: vendor, receipt number, date, subtotal, GST and total, plus line items
- OCR for scanned PDFs and photos (JPG, PNG, WebP) with PaddleOCR: straightens skewed photos, turns sideways and upside-down pages, evens out shadows and fading; poor reads go to review instead of guessing
- Multi-receipt files: one receipt per sheet, and PDFs split into receipts by content
- A background worker with automatic recovery and retries
- Categories: eight built-in ones, plus custom categories you can add, rename and delete
- Validation: line items and subtotal + tax must match the total (within ₹1), dates must fall in this or last financial year, and repeated receipts are caught; problems are kept as warnings to look at
- Review page: the original next to what was extracted, every field and line item editable, categories, reject, and "Mark as OK" for warnings
- Summary cards and counts on the Files page, and error reports as PDF (one file, or all flagged files as a zip)
- Health and readiness checks for the API, database and queue

**Planned**

- HEIC photos (for now, convert to JPG or PNG)
- Opt-in AI extraction per file or per batch, with a confirmation step and a daily cap
- Query page with filters and plain-English questions

## Architecture

```mermaid
flowchart LR
  UI[React app] -->|HTTP only| API[FastAPI]
  API --> DB[(PostgreSQL)]
  API --> FS[File storage]
  API --> Q[Job queue on Redis]
  Q --> EX[Library extractors]
  Q -. only after approval .-> AI[Claude or OpenAI]
```

The FastAPI backend does all the work; the React app is purely a client of its HTTP API, with TypeScript types generated from the backend's OpenAPI spec. Every extractor returns the same receipt schema, so parsers and providers can be swapped independently.

Each uploaded file moves through a fixed pipeline: **Receive → Register → Detect → Extract → Normalize → Validate → Store**. Every stage is idempotent and records its status, and files that fail validation wait in *Needs review* for a person.

## Tech stack

| Layer | Technologies |
| --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Data | PostgreSQL 16, Redis 7, ARQ workers |
| Extraction | pandas, openpyxl, xlrd, pdfplumber, pypdfium2, OpenCV, PaddleOCR |
| AI (opt-in) | Anthropic and OpenAI SDKs behind one interface |
| Frontend | React, TypeScript, Vite, Tailwind CSS v4, TanStack Query and Table, React Router |
| Observability | structlog (JSON in production), request ids on every log line |
| Tooling | uv, ruff, pytest, ESLint, Prettier, Vitest, Docker Compose |

## Getting started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with Compose v2)
- About 6 GB of disk for the images and about 3 GB of memory for Docker (the OCR worker peaks near 400 MB while reading a photo)

### Run the full stack

```bash
git clone https://github.com/manasrai1406/parchi.git
cd parchi
cp .env.example .env
docker compose up --build
```

| Service | URL |
| --- | --- |
| Web app | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |

Database migrations run automatically when the API starts, and a background worker processes uploaded files. The sidebar shows **Connected** once the API, database and Redis are all reachable.

To try it with sample receipts, generate a set of synthetic invoices, receipts, photos and scans (with their expected answers in `answers.json`) and upload them on the Upload page:

```bash
docker compose exec api python scripts/make_samples.py   # writes to data/samples/synthetic/
```

OCR (PaddleOCR) is included in the Docker image, with its models downloaded at build time, so images never leave your machine. A photo takes a few seconds to read on a laptop CPU; the first one after a restart is a little slower while the models load.

To stop everything:

```bash
docker compose down
```

## Development

The backend and frontend can also be run directly on your machine, with PostgreSQL and Redis still in Docker:

```bash
docker compose up -d postgres redis
```

### Backend

Requires [uv](https://docs.astral.sh/uv/). Run from `backend/`:

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn parchi.api.main:app --reload --loop asyncio:SelectorEventLoop
```

> The `--loop` flag is needed on Windows, where the default event loop is not supported by the async PostgreSQL driver. It is harmless elsewhere.

To process uploads, also run the worker (from `backend/`, on Linux or macOS; on Windows use Docker):

```bash
uv run arq parchi.worker.WorkerSettings
```

OCR is an optional extra (`uv sync --extra ocr`, about 1.5 GB). Without it, scans and photos wait in review with a note; everything else works.

### Frontend

Requires Node.js 22+. Run from `frontend/`:

```bash
npm install
npm run dev
```

The dev server proxies `/api/*` to the backend at `http://localhost:8000`.

### Tests and checks

```bash
# Backend (from backend/). Database tests run when TEST_DATABASE_URL is set.
uv run ruff check . && uv run ruff format --check .
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/parchi_test uv run pytest

# Or inside Docker, against the bundled test database
docker compose exec api pytest

# Frontend (from frontend/)
npm run lint && npm run format:check
npm test
npm run build
```

### Benchmarking the readers

Scores every sample with known answers (synthetic ones, and your own in `data/samples/real/` with an `answers.json` in the same format) and prints per-field accuracy:

```bash
docker compose exec api python scripts/benchmark_extractors.py
```

### Regenerating API types

After changing an endpoint, regenerate the frontend's types from the backend's OpenAPI spec:

```bash
cd frontend
npm run gen:api:export && npm run gen:api
```

## Configuration

Settings are read from environment variables (or `.env`). See [`.env.example`](.env.example) for the full list.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/parchi` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379` | Job queue |
| `STORAGE_DIR` | `data/uploads` | Where original files are stored |
| `MAX_UPLOAD_MB` | `20` | Maximum size per file |
| `MAX_FILES_PER_BATCH` | `50` | Maximum files per upload batch |
| `APP_ENV` | `development` | `development`, `production` or `test` |
| `APP_TIMEZONE` | `Asia/Kolkata` | Timezone for reference-number years and the daily AI cap |
| `LOG_LEVEL` | `info` | Log verbosity |
| `LOCAL_USER_NAME` | `local user` | Name recorded on approvals (there is no login in v1) |
| `AI_ENABLED` | `false` | Master switch for every AI call |
| `AI_DAILY_CAP` | `50` | Approved AI extractions allowed per day |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | — | Set only for the providers you use |

Never commit `.env` or anything under `data/`.

## Project structure

```
parchi/
├── backend/
│   ├── src/parchi/
│   │   ├── api/            FastAPI app, middleware, error handling, routes
│   │   ├── db/             models, enums, sessions, queries
│   │   ├── extraction/     Excel/CSV, PDF and OCR readers, image cleanup, normalization
│   │   ├── ingestion/      receive, register, storage, detection, deletion
│   │   ├── pipeline/       orchestrator, worker jobs, queue, recovery
│   │   ├── review/         saving edits, rejecting, error reports
│   │   ├── validation/     required fields, arithmetic, dates, duplicates
│   │   ├── schemas/        API request and response models
│   │   ├── config.py       settings
│   │   ├── logging.py      structured logging
│   │   └── worker.py       background worker settings
│   ├── migrations/         Alembic migrations
│   ├── scripts/            maintenance scripts
│   └── tests/              unit and integration tests
├── frontend/
│   └── src/
│       ├── api/            API client, generated types, query hooks
│       ├── components/     shared UI components
│       ├── pages/          Upload, Files, Review, Query
│       └── styles/         design tokens
├── docs/                   plan, decisions and UI designs
├── docker/                 container setup
└── docker-compose.yml
```

## API

Interactive documentation is available at `/docs` when the API is running. Current endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/batches` | Create an upload batch |
| `POST` | `/batches/{id}/files` | Upload one file into a batch |
| `GET` | `/batches/{id}` | A batch and the status of its files |
| `GET` | `/files` | List files: filter by status, search, the review queue, paginate |
| `GET` | `/files/summary` | Counts per status for the summary cards and badges |
| `GET` | `/files/error-reports.zip` | Originals of all files needing attention, plus one PDF report |
| `GET` | `/files/{id or ref}` | One file, with its receipts, line items, flags and extraction runs |
| `GET` | `/files/{id or ref}/download` | The original file (`?inline=true` previews PDFs and images) |
| `GET` | `/files/{id or ref}/error-report` | A PDF of the file's problems and what each reader found |
| `PUT` | `/files/{id or ref}/receipts` | Save a person's corrections; the file becomes resolved |
| `POST` | `/files/{id or ref}/reject` | Reject a file (not a receipt, bad scan) |
| `POST` | `/flags/{id}/resolve` | Mark a warning as looked at and OK |
| `DELETE` | `/files/{id or ref}` | Delete a file and its extracted data |
| `GET` | `/categories` | Built-in and custom categories, with usage counts |
| `POST` | `/categories` | Add a custom category |
| `PATCH` | `/categories/{id}` | Rename a custom category |
| `DELETE` | `/categories/{id}` | Delete an unused custom category |
| `GET` | `/health` | Liveness |
| `GET` | `/health/ready` | Readiness of PostgreSQL and Redis |

All errors share one shape, `{ "code", "message", "request_id" }`, so any error shown in the UI can be traced to its log lines.

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1. Foundation | Project setup, Docker Compose, settings, logging, database schema, health checks | ✅ Done |
| 2. Upload and register | Upload, hashing, reference numbers, duplicates, Files page, downloads | ✅ Done |
| 3. Library extraction | File-type detection, Excel/CSV and digital PDF extractors, background worker | ✅ Done |
| 4. Validation and review | Validation rules, flags, Review page, manual editing, error reports | ✅ Done |
| 5. OCR and images | Scanned PDFs and photos, image preprocessing (HEIC later) | ✅ Done |
| 6. Opt-in AI | Claude and OpenAI adapters, approval enforcement, daily cap, comparison view | Next |
| 7. Query and hardening | Filters, plain-English queries, recovery job, integration tests | Planned |

## Documentation

- [`docs/PLAN.md`](docs/PLAN.md): the full plan, covering data model, pipeline, API and phases
- [`docs/decisions.md`](docs/decisions.md): every decision made since the plan, and why
- [`docs/design/`](docs/design/): UI designs and design tokens

## License

To be added.
