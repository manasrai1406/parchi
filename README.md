# Parchi

**Turn the slips of paper India runs on into data you can trust.**

Parchi reads receipts in any form (phone photos, scanned PDFs, digital invoices, Excel sheets), extracts the vendor, date, GST and totals, checks that the numbers add up, and turns them into a clean, queryable dataset. It uses deterministic open-source tools first, keeps a person in charge of every judgement call, and brings in generative AI (Claude, OpenAI or Gemini) only when a person explicitly approves it.

> **Status:** feature-complete for version 1. All seven planned phases are done, plus login and roles, learning from corrections, and category management. 49 design decisions are recorded in [`docs/decisions.md`](docs/decisions.md).

---

## Contents

- [Why Parchi](#why-parchi)
- [How it works](#how-it-works)
- [Engineering highlights](#engineering-highlights)
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

*Parchi* (पर्ची) is Hindi for a slip of paper: the bill from the chai stall, the petrol pump receipt, the kirana store's handwritten memo, the cinema ticket printed on thermal paper. India's small businesses and households run on them, and they are among the hardest documents to turn into data:

- **Every layout is different.** One vendor prints *Grand Total*, the next *Net Payable*, a cinema prints *Agreegate* (misspelt, but real). Tax is split into CGST and SGST, sometimes on one line.
- **The inputs are messy.** Crumpled photos taken at an angle, faded thermal prints, scans upside down, spreadsheets with a different column order every month.
- **The details are local.** Indian digit grouping (₹1,23,456.50), day-first dates, and a financial year that starts on 1 April.
- **A wrong number looks exactly like a right one.** An expense total that is quietly misread is worse than one that is missing.

The easy answer today is to send every document to a large language model. Parchi takes a different position: **AI should be a specialist you consult, not the default.** Most receipts can be read exactly and cheaply by deterministic code; what can't be read goes to a person first; and an LLM is consulted only when that person decides it is worth sending the file out. The result is a system that is:

- **Trustworthy:** every number is checked (line items and subtotal + tax must add up to the total within ₹1), every uncertain read is flagged instead of guessed, and every change is signed by a person.
- **Private by default:** OCR runs on your own machine. A receipt leaves it only with a recorded approval.
- **Cost-aware:** AI calls are off by default, capped per day, cached per file, and counted in tokens.
- **Getting better with use:** when you correct a receipt, Parchi learns the label that vendor prints and reads their next receipt by itself.
- **Useful to analysts:** the output is a clean, typed dataset (exact decimals, normalized vendors, categories) that you can filter, total, question in plain English and export as CSV.

## How it works

```mermaid
flowchart LR
  A[Upload: photo, PDF, Excel, CSV] --> B[Detect type from the bytes]
  B --> C[Read with libraries: pandas, pdfplumber, OCR]
  C --> L[Apply labels learned from past corrections]
  L --> D{Checks pass?}
  D -- yes --> E[(Stored: Parsed)]
  D -- no --> F[Needs review]
  F --> G[A person fixes it]
  F -. only if approved .-> H[AI read: Claude, OpenAI or Gemini]
  H --> D
  G --> E
  G --> M[Parchi learns the vendor's labels]
  E --> Q[Query: filters, plain-English questions, CSV]
```

1. **Read deterministically.** File type is detected from the bytes, not the name. Spreadsheets are read with pandas, digital PDFs with pdfplumber, and photos and scans with PaddleOCR after the image is straightened, turned the right way up and evened out.
2. **Check everything.** Required fields, arithmetic, plausible dates within this or last financial year, and duplicate receipts. A failed check becomes a warning a person can see; a low-confidence read goes to *Needs review*.
3. **Keep a person in the loop.** The Review page shows the original file next to what was read, and every field is editable. Saving records the correction as a new run, so earlier attempts are never overwritten.
4. **Consult AI only with approval.** From the Review page, or for a batch on the Files page, a person can approve an AI read. The dialog says which provider, what is sent and how many approvals are left today. The AI's answer goes through the same checks and is shown side by side with the library's; disagreements are flagged for the person to settle.
5. **Learn from corrections.** When a person fixes a total the reader missed, Parchi finds that amount in the text it read, learns the words in front of it as that vendor's label, and uses it on the vendor's next receipt. A label learned from three vendors is used for everyone.
6. **Query.** Filter by date, vendor, category and amount; ask "fuel in August" or "top 5 receipts this financial year"; see the SQL that ran; export CSV.

## Engineering highlights

**Generative AI, used responsibly**
- One provider interface with three adapters (Anthropic Claude, OpenAI Responses API, Google Gemini), all returning the same JSON-schema-validated receipt structure.
- **Human approval is enforced by the system, not the UI:** a provider can only be called with an approval object built from a stored run, and a database constraint rejects any AI run without an approver and timestamp. A test proves no provider is called without approval.
- Cost and safety controls: a master switch (off by default), a daily cap, a cache keyed by file hash, provider and model, token counts on every run, and clear handling of refusals, cut-off answers and provider overload.
- AI output is never trusted blindly: it goes through the same validation as library output, and a disagreement with the library on vendor, date or total is flagged for a person to settle.

**Data quality and analytics**
- Exact money handling (decimals, never floats), Indian number formats, GST split into CGST, SGST and IGST, and financial-year-aware dates.
- A plain-English question reader that turns "food over ₹500 last month" into filters with **rules, not an LLM**: predictable, free and private. It shows how the question was understood and the SQL that ran.
- Queries run under a **read-only PostgreSQL role** that can see only one view, inside a read-only transaction with a timeout.
- CSV export that is safe to open in Excel: cells that could run as formulas are escaped.

**A system that improves with use**
- Vendor-specific label learning from reviewer corrections. It refuses to learn when the evidence is ambiguous, and it records who taught each label.
- Real receipts can be kept as a private, local regression suite (`scripts/check_real_samples.py`), so any change to a reader that breaks a real receipt is caught before it ships.
- An extraction benchmark scores every reader, field by field, against known answers.

**Production engineering**
- A staged, idempotent pipeline on an async FastAPI backend with an ARQ worker on Redis, automatic recovery of stuck jobs, and retries with backoff.
- Content-addressed storage (SHA-256) with duplicate detection that is safe under concurrent uploads.
- Login with Argon2id password hashing, server-side sessions in httpOnly `SameSite=Strict` cookies, lockout after repeated failures, and three roles checked on every endpoint. A test calls every route to prove none is open, or writable by the wrong role.
- Structured JSON logging with request, user, file and run ids on every line, and never any receipt contents or secrets.
- 450+ backend tests (pytest, many against a real PostgreSQL) and 60+ frontend tests (Vitest), with CI running ruff, pytest, ESLint, Prettier, Vitest and a production build on every push.
- Every non-obvious choice is written down with its reasoning in [`docs/decisions.md`](docs/decisions.md).

## Features

**Getting receipts in**
- Drag-and-drop upload of PDFs, photos (JPG, PNG, WebP), Excel (.xlsx, .xls) and CSV, with per-file progress
- Files stored by content hash, each with a reference number (`REF-2026-000412`) shown everywhere and in every log line
- Duplicate detection: identical files are caught, and you decide whether to keep a copy

**Reading them**
- Spreadsheets and digital PDFs: vendor, receipt number, date, subtotal, GST and total, plus line items
- OCR for photos and scans: straightens skewed photos, turns sideways and upside-down pages, evens out shadows and fading
- Several receipts in one file: one per sheet, or PDFs split by content
- Labels learned per vendor from your corrections

**Checking and fixing**
- Validation of required fields, arithmetic (within ₹1), dates and duplicates, kept as warnings to look at
- A Review page with the original beside the extracted values; every field and line item editable; reject, and "Mark as OK" for warnings
- Opt-in AI reads with Claude, OpenAI or Gemini, one file or a batch, compared with the library's result
- Error reports as PDF, for one file or all flagged files as a zip

**Organising and analysing**
- Categories: eight built-in ones plus your own, added from the Review page or managed on the Categories page
- A Query page with date (this financial year by default), vendor, category and amount filters; the count, total and average; pages of 50; CSV export
- Plain-English questions, with the interpretation and SQL shown

**Running it**
- Login and sign-up; roles for viewers, reviewers and admins; a Users page for admins
- A background worker with recovery and retries, and health and readiness checks
- A local test set of your real receipts, and a benchmark for the readers

## Architecture

```mermaid
flowchart LR
  UI[React app] -->|HTTP only| API[FastAPI]
  API --> DB[(PostgreSQL)]
  API --> FS[File storage]
  API --> Q[Job queue on Redis]
  Q --> EX[Library extractors and OCR]
  Q -. only after approval .-> AI[Claude, OpenAI or Gemini]
```

The FastAPI backend does all the work; the React app is purely a client of its HTTP API, with TypeScript types generated from the backend's OpenAPI spec. Every extractor and every AI provider returns the same receipt schema, so readers and providers can be swapped independently.

Each uploaded file moves through a fixed pipeline: **Receive → Register → Detect → Extract → Apply learned labels → Validate → Store**. Every stage is idempotent and records its status, and files that fail validation wait in *Needs review* for a person.

## Tech stack

| Layer | Technologies |
| --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Data | PostgreSQL 16, Redis 7, ARQ workers |
| Extraction | pandas, openpyxl, xlrd, pdfplumber, pypdfium2, OpenCV, PaddleOCR |
| Generative AI (opt-in) | Anthropic, OpenAI and Google Gen AI SDKs behind one interface, JSON-schema structured output |
| Security | Argon2id (argon2-cffi), server-side sessions, role-based access, a read-only database role for queries |
| Frontend | React, TypeScript, Vite, Tailwind CSS v4, TanStack Query and Table, React Router, React Hook Form, Zod |
| Observability | structlog (JSON in production), request and user ids on every log line |
| Tooling | uv, ruff, pytest, ESLint, Prettier, Vitest, Docker Compose, GitHub Actions |

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

Create the first admin account, then log in at http://localhost:5173 with it. The password you type here is temporary: Parchi asks for a new one at the first login. Other people can create their own accounts from the login page (they start as viewers), or you can add them on the **Users** page.

```bash
docker compose exec api python scripts/create_admin.py <username> "<Your name>"
```

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
| `ALLOW_SIGNUP` | `true` | Let people create their own Viewer accounts; `false` means only admins add people |
| `REAL_SAMPLES_DIR` | `/data/samples/real` in Docker | Where receipts kept as tests are copied (unset: the option is off) |
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
│   │   ├── extraction/     Excel/CSV, PDF and OCR readers, image cleanup, labels, learned labels
│   │   ├── ingestion/      receive, register, storage, detection, deletion
│   │   ├── pipeline/       orchestrator, worker jobs, queue, recovery
│   │   ├── query/          Query filters, plain-English question reader, read-only access
│   │   ├── review/         saving edits, learning from corrections, test set, error reports
│   │   ├── validation/     required fields, arithmetic, dates, duplicates
│   │   ├── schemas/        API request and response models
│   │   ├── config.py       settings
│   │   ├── logging.py      structured logging
│   │   └── worker.py       background worker settings
│   ├── migrations/         Alembic migrations
│   ├── scripts/            create an admin, samples, benchmark, real-receipt checks
│   └── tests/              unit and integration tests
├── frontend/
│   └── src/
│       ├── api/            API client, generated types, query hooks
│       ├── auth/           session, login state and roles
│       ├── components/     shared UI components
│       ├── pages/          Login, Upload, Files, Review, Query, Categories, Users
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
| `PUT` | `/files/{id or ref}/receipts` | Save a person's corrections; the file becomes resolved, and labels are learned |
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
| 6. Opt-in AI | Claude, OpenAI and Gemini adapters, approval enforcement, daily cap, cache, comparison view | ✅ Done |
| 7. Query and hardening | Filters, plain-English queries on read-only access, CSV export, CI | ✅ Done |
| Beyond the plan | Login and roles, sign-up, learning labels from corrections, real-receipt test set, category management | ✅ Done |
| Next | Cloud deployment and object storage, exports beyond CSV | Planned |

## Documentation

- [`docs/PLAN.md`](docs/PLAN.md): the original plan, covering data model, pipeline, API and phases
- [`docs/decisions.md`](docs/decisions.md): every decision made since the plan, and why (49 so far)
- [`docs/design/`](docs/design/): UI designs and design tokens

