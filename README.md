# Parchi

**Receipt ingestion, extraction and review — library-first, with AI only when a person approves it.**

Parchi takes in receipts as PDFs, photos and spreadsheets, extracts them with open-source libraries, validates the results, and stores them in PostgreSQL. A React app lets people upload files, follow their progress, review and fix problems, and query the data. AI extraction (Claude, OpenAI or Gemini) is strictly opt-in: it never runs unless a person approves it, and every approval is recorded.

> **Status:** all seven planned phases are complete (foundation, upload and registration, library extraction, validation and review, OCR, opt-in AI, query and hardening). See the [roadmap](#roadmap).

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
- Categories: eight built-in ones, plus custom categories you add from the Review page's Category list or the Categories page, where you can also rename and delete them
- Validation: line items and subtotal + tax must match the total (within ₹1), dates must fall in this or last financial year, and repeated receipts are caught; problems are kept as warnings to look at
- Review page: the original next to what was extracted, every field and line item editable, categories, reject, and "Mark as OK" for warnings
- Learns from your corrections: when you fix a total, subtotal or tax, Parchi remembers the label that vendor prints (such as "Agreegate") and reads their next receipt by itself; a label learned from three vendors is used for everyone
- Your real receipts as a local test set: tick "Keep as a test receipt" when resolving, and `scripts/check_real_samples.py` checks the readers still get them right (kept only on your machine)
- Summary cards and counts on the Files page, and error reports as PDF (one file, or all flagged files as a zip)
- Health and readiness checks for the API, database and queue
- Login with username and password, sign-up for new people (as viewers), and three roles: viewers look and query, reviewers also upload, fix and approve AI, admins also delete files and manage users; every action is signed with the username

- Opt-in AI extraction with Claude, OpenAI or Gemini, one file or a batch, only after you approve it: the approval dialog says exactly what is sent, approvals are recorded with who, when and which provider, results are cached per file and provider, and a daily cap applies
- AI results side by side with the library result on the Review page; disagreements are flagged for you to choose
- Query page: filters for dates (this financial year by default), vendor, category and amount, with the count, total and average, pages of 50, and CSV export
- Plain-English questions such as "fuel in August" or "top 5 receipts this financial year", read by built-in rules (no AI): the page shows how the question was understood and the SQL that ran, on read-only database access
- CI on every push: ruff, pytest, ESLint, Prettier, Vitest and a production build

**Planned**

- Cloud deployment, and exports beyond CSV

## Architecture

```mermaid
flowchart LR
  UI[React app] -->|HTTP only| API[FastAPI]
  API --> DB[(PostgreSQL)]
  API --> FS[File storage]
  API --> Q[Job queue on Redis]
  Q --> EX[Library extractors]
  Q -. only after approval .-> AI[Claude, OpenAI or Gemini]
```

The FastAPI backend does all the work; the React app is purely a client of its HTTP API, with TypeScript types generated from the backend's OpenAPI spec. Every extractor returns the same receipt schema, so parsers and providers can be swapped independently.

Each uploaded file moves through a fixed pipeline: **Receive → Register → Detect → Extract → Normalize → Validate → Store**. Every stage is idempotent and records its status, and files that fail validation wait in *Needs review* for a person.

## Tech stack

| Layer | Technologies |
| --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Data | PostgreSQL 16, Redis 7, ARQ workers |
| Extraction | pandas, openpyxl, xlrd, pdfplumber, pypdfium2, OpenCV, PaddleOCR |
| AI (opt-in) | Anthropic, OpenAI and Google Gen AI SDKs behind one interface |
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

Database migrations run automatically when the API starts, and a background worker processes uploaded files.

Create the first admin account, then log in at http://localhost:5173 with it. The password you type here is temporary: Parchi asks for a new one at the first login. Other people can create their own accounts from the login page (they start as viewers), or you can add them on the **Users** page.

```bash
docker compose exec api python scripts/create_admin.py <username> "<Your name>"
```
 The sidebar shows **Connected** once the API, database and Redis are all reachable.

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

### Checking the readers on your own receipts

Receipts you keep as tests on the Review page are copied, with the answer you confirmed, to `data/samples/real/` (never committed). Re-read them all after changing a reader:

```bash
docker compose exec api python scripts/check_real_samples.py                # with learned labels
docker compose exec api python scripts/check_real_samples.py --library-only # built-in labels only
```

It lists each receipt as `ok` or `FAIL` with the fields read wrong, and exits with 1 if any failed.

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
| `COOKIE_SECURE` | `false` | Send the login cookie over HTTPS only; set `true` when serving over HTTPS |
| `SESSION_DAYS` | `7` | How long a login lasts without being used |
| `REAL_SAMPLES_DIR` | `/data/samples/real` in Docker | Where receipts kept as tests are copied (unset: the option is off) |
| `ALLOW_SIGNUP` | `true` | Let people create their own Viewer accounts; `false` means only admins add people |
| `AI_ENABLED` | `false` | Master switch for every AI call |
| `AI_DAILY_CAP` | `50` | Approved AI extractions allowed per day |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | — | Set only for the providers you use |
| `ANTHROPIC_MODEL`, `OPENAI_MODEL`, `GEMINI_MODEL` | `claude-sonnet-5`, `gpt-6-sol`, `gemini-3.6-flash` | Models used for approved AI reads |

Never commit `.env` or anything under `data/`.

### Turning on AI

AI is off by default and nothing is ever sent without an approval. To use it, add a key for at least one provider to `.env`, switch it on, and restart:

```bash
AI_ENABLED=true
ANTHROPIC_API_KEY=sk-ant-...     # and/or OPENAI_API_KEY=sk-... or GEMINI_API_KEY=...
```

```bash
docker compose up -d api worker
```

Then choose **Extract with AI…** on a file in review (or select several on the Files page). The dialog shows the provider, what will be sent, and how many approvals are left today.

## Project structure

```
parchi/
├── backend/
│   ├── src/parchi/
│   │   ├── ai/             provider interface, Claude, OpenAI and Gemini adapters, prompt
│   │   ├── api/            FastAPI app, middleware, error handling, routes
│   │   ├── auth/           passwords, sessions, roles
│   │   ├── db/             models, enums, sessions, queries
│   │   ├── extraction/     Excel/CSV, PDF and OCR readers, image cleanup, normalization
│   │   ├── ingestion/      receive, register, storage, detection, deletion
│   │   ├── pipeline/       orchestrator, worker jobs, queue, recovery
│   │   ├── query/          Query filters, plain-English question reader, read-only access
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

Interactive documentation is available at `/docs` when the API is running. Every endpoint except the health checks, login and sign-up needs a logged-in user, and each checks the role (viewer, reviewer or admin). Current endpoints:

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
| `POST` | `/files/{id or ref}/ai-extract` | Approve one file for an AI read (`provider`, `approved: true`) |
| `POST` | `/files/ai-extract` | Approve several files at once |
| `GET` | `/ai/usage` | Approved AI reads today, the daily cap, and which providers are set up |
| `DELETE` | `/files/{id or ref}` | Delete a file and its extracted data |
| `GET` | `/categories` | Built-in and custom categories, with usage counts |
| `POST` | `/categories` | Add a custom category |
| `PATCH` | `/categories/{id}` | Rename a custom category |
| `DELETE` | `/categories/{id}` | Delete an unused custom category |
| `GET` | `/receipts` | Receipts from parsed and resolved files: filter by dates, vendor, category and amount; totals and pages of 50 |
| `GET` | `/receipts/export.csv` | The same receipts as CSV, every page |
| `GET` | `/vendors` | Vendor names that have receipts, for the vendor filter |
| `POST` | `/query/ask` | A plain-English question: how it was read, the SQL that ran, and the first page |
| `POST` | `/auth/login` | Log in; sets the session cookie |
| `POST` | `/auth/signup` | Create your own account, as a Viewer, and log in |
| `GET` | `/auth/options` | Whether sign-up is offered |
| `POST` | `/auth/logout` | Log out |
| `GET` | `/auth/me` | Who is logged in |
| `PUT` | `/auth/password` | Change your own password |
| `GET` | `/users` | Accounts (admins) |
| `POST` | `/users` | Add a user with a temporary password (admins) |
| `PATCH` | `/users/{id}` | Change a name or role, deactivate or reactivate (admins) |
| `POST` | `/users/{id}/password` | Reset a password to a temporary one (admins) |
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
| 5. OCR and images | Scanned PDFs and photos (JPG, PNG, WebP), image preprocessing | ✅ Done |
| 6. Opt-in AI | Claude and OpenAI adapters, approval enforcement, daily cap, comparison view | ✅ Done |
| 7. Query and hardening | Filters, plain-English queries on read-only access, CSV export, CI | ✅ Done |

## Documentation

- [`docs/PLAN.md`](docs/PLAN.md): the full plan, covering data model, pipeline, API and phases
- [`docs/decisions.md`](docs/decisions.md): every decision made since the plan, and why
- [`docs/design/`](docs/design/): UI designs and design tokens

## License

To be added.
