# Decisions

A log of decisions made while building Parchi, newest last. `docs/PLAN.md` holds the original plan; this file records where we settled an open point or changed something. Each entry says what was decided and why.

## D-001 Single local user for approvals

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** There is no login in v1. `approved_by` and `resolved_by` are filled with one name taken from a `LOCAL_USER_NAME` setting.
- **Why:** Login and roles are listed under "Left for later". The audit trail still needs a name on every approval.

## D-002 Vendors table

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** Add a `vendors` table that maps a raw vendor name (as printed) to a normalized name. Receipts reference a vendor row instead of storing a free-text vendor.
- **Why:** The same vendor is printed in many ways. Queries and duplicate checks need one name per vendor.

## D-003 Receipt category with manual override

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** Receipts store an automatic category and an optional manual override. The effective category is the override when present, otherwise the automatic one.
- **Why:** A person must be able to correct a category without losing what the system assigned.

## D-004 Exactly one accepted run per file

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** A database constraint allows at most one `extraction_runs` row with `accepted = true` per file.
- **Why:** Receipts come from the accepted run. Two accepted runs would make it unclear which result is the truth.

## D-005 Timestamps on every table

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** Every table has `created_at` and `updated_at`.
- **Why:** Consistent auditing and debugging across all tables.

## D-006 Duplicate uploads ask the person first

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** When an upload has the same SHA-256 as an existing file, the person is told the file already exists (with its reference number) and asked whether to save it anyway. No rejects it and nothing is stored. Yes saves it as a normal new file with its own reference number, and it goes through the pipeline like any other file. `files.sha256` is indexed but **not unique**. A nullable `files.duplicate_of_id` links an accepted copy to the earliest file with the same hash.
- **Why:** The person sometimes needs to keep an identical file on purpose. Any receipts counted twice are caught by the `duplicate_receipt` check.
- **Changes the plan:** Hard rule 5 ("`sha256` is unique on `files`") no longer holds. Retries of Register must be made idempotent some other way (settled in Phase 2).

## D-007 Remove the `duplicate` file status

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** `duplicate` is removed from the file statuses. A declined duplicate is never stored, and an accepted one gets the normal statuses.
- **Why:** After D-006, nothing ever sets it.

## D-008 No sequence gap or out-of-order checks in v1

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** Drop the sequence gap check and the out-of-order number check. The `sequence_gap` and `out_of_order` flag types are removed, and receipts store no prefix or integer split of the receipt number. Duplicate-receipt checks (vendor, number, total) and a plain "date is plausible" check stay.
- **Why:** Receipts come from many vendors, so the printed numbers do not form one series. Both checks are easy to add back later.
- **Changes the plan:** Hard rule 7 and roadmap item "a sequence gap is flagged" in the phase 4 exit check are dropped.

## D-009 Fixed category list with a per-vendor default

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** Categories are a fixed list: `fuel`, `travel`, `food`, `office`, `utilities`, `maintenance`, `services`, `other`. Each vendor has an optional `default_category`, which fills `receipts.category_auto`. A person can set `receipts.category_override`. The effective category is the override if set, otherwise the automatic one. The database checks values against the list.
- **Why:** A fixed list keeps queries and totals clean. The vendor default gives automatic categories without rules or AI.

## D-010 Added dependencies

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** Approved additions to the stack. Backend: `psycopg[binary]` (async SQLAlchemy driver), `pydantic-settings`, `uvicorn`, and `httpx` for tests. Frontend: `clsx`, `tailwind-merge`, `class-variance-authority`, `@fontsource` packages for self-hosted fonts, and Vitest with `@testing-library/react` and `jsdom`.
- **Why:** Needed for Phase 1 and not covered by the listed stack. Self-hosted fonts avoid calls to Google Fonts.

## D-011 Parchi has its own git repository

- **Date:** 2026-09-26 (Phase 1)
- **Decision:** Run `git init` inside `parchi/` on branch `main`. The enclosing Desktop repository is left alone.
- **Why:** That repository holds unrelated personal files.

## D-012 Schema conventions

- **Date:** 2026-09-26 (Phase 1)
- **Decision:**
  - Primary keys are `bigint` identity columns. `ref_no` is the public identifier.
  - Enums are `varchar` columns with named CHECK constraints generated from Python `StrEnum`s, not native PostgreSQL enum types.
  - A trigger keeps `updated_at` current on every table.
  - Constraints and indexes follow a fixed naming convention, and every foreign key column is indexed.
  - `files.uploaded_at` is dropped in favor of `created_at`.
  - New columns beyond the plan: `files.status_changed_at`, `files.attempts`, `extraction_runs.model`, `extraction_runs.finished_at`, `flags.dedupe_key`.
- **Why:** Native enums are awkward to change in migrations. The added columns support the recovery job, retry limits, the AI audit trail and re-runnable flag writes.

## D-013 Defaults accepted without discussion

- **Date:** 2026-09-26 (Phase 1)
- **Decision:**
  1. Vendor, receipt date and total are required, so they are NOT NULL on `receipts`.
  2. Receipt suffixes may exceed `-99` (two or more digits).
  3. The daily AI cap and the year in reference numbers use `APP_TIMEZONE`, default `Asia/Kolkata`. The reference counter is one global sequence that never resets.
  4. Changing a file's accepted run deletes and recreates its receipts in one transaction, reusing the same suffixes. Flags on deleted receipts keep the file link (`receipt_id` set to NULL).
  5. The plan's "one library run per file" is a partial unique index. Revisit in Phase 7 when the reprocess script is built.
  6. Per-type confidence thresholds and fallback chains live in Python config, not a database table.
  7. No sign constraint on amounts in the database. Validation decides what is allowed.
  8. Filenames are trimmed, Unicode-normalized and cut to 255 characters. A name with a path separator or control character is rejected.
  9. `/health` is liveness only. `/health/ready` checks PostgreSQL and Redis.
  10. The ARQ worker service is added to Docker Compose in Phase 3, not Phase 1.
  11. Tests use a separate `parchi_test` database on the Compose PostgreSQL, without testcontainers.
  12. No CI until there is a remote repository.
  13. Versions: Python 3.12, PostgreSQL 16, Redis 7, Node 22, Tailwind v4.
  14. Tax is one column, with no CGST/SGST/IGST split and no GSTIN.
- **Why:** Proposed during Phase 1 planning and accepted as a group.

## D-014 Phase 1 tooling details

- **Date:** 2026-09-26 (Phase 1)
- **Decision:**
  1. The frontend calls the API under `/api`. The Vite dev server forwards `/api/*` to FastAPI with the prefix removed, so no CORS setup is needed.
  2. API types are generated from FastAPI's OpenAPI spec. `backend/scripts/export_openapi.py` writes `frontend/openapi.json` without starting a server, and `openapi-typescript` turns it into `frontend/src/api/schema.d.ts`. Both files are committed.
  3. Theme C colors are CSS variables mapped into Tailwind v4 `@theme` tokens, so a light theme only has to override the variables.
  4. Pinned versions: TypeScript `~5.9`, because `openapi-typescript` needs TypeScript 5. jsdom `^26`, because jsdom 27 needs Node 22.12 or newer.
  5. When the API runs natively on Windows, uvicorn is started with `--loop asyncio:SelectorEventLoop`, because psycopg's async mode cannot use Windows' default Proactor loop. Docker (Linux) is unaffected.
  6. `/health/ready` powers a "System" card at the bottom of the sidebar. The "AI approved today" card from the design comes in Phase 6, when `GET /ai/usage` exists.
- **Why:** These came up while building Phase 1 and are recorded so later phases do not undo them by accident.

## D-015 Confirming a duplicate re-sends the file

- **Date:** 2026-09-26 (Phase 2)
- **Decision:** When an upload matches an existing file's SHA-256, the API saves nothing and answers with the matching file (id, reference number, name). If the person chooses to save it anyway, the browser uploads the file again with `confirm_duplicate=true`. The new row's `duplicate_of_id` points to the earliest file with that hash, and it shares the stored bytes.
- **Why:** Chosen by the user. It keeps the server stateless: nothing is held while the person decides.

## D-016 Upload limits and accepted types

- **Date:** 2026-09-26 (Phase 2)
- **Decision:** At most 20 MB per file and 50 files per batch (settings `MAX_UPLOAD_MB` and `MAX_FILES_PER_BATCH`). At upload, only these extensions are accepted: `.pdf`, `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.xlsx`, `.xls`, `.csv`. Anything else is refused at once. Phase 3 still checks the real bytes, so a renamed file is caught there.
- **Why:** 20 MB matches the design copy. Refusing unsupported files early gives a clearer message than a later `unreadable` flag.

## D-017 One upload request per file

- **Date:** 2026-09-26 (Phase 2)
- **Decision:** `POST /batches` creates an empty batch. Each file is then sent on its own to `POST /batches/{id}/files`. This replaces the plan's single `POST /batches` carrying every file.
- **Why:** Real progress per file, and one failed file does not fail the rest of the batch.
- **Changes the plan:** The API table in PLAN.md.

## D-018 Registering the same bytes twice at the same moment

- **Date:** 2026-09-26 (Phase 2)
- **Decision:** Register takes a PostgreSQL advisory lock on the file's hash for the length of its transaction. Two simultaneous identical uploads are therefore handled one after the other: the first is saved, the second is reported as a duplicate. Stored bytes are removed after a failed insert only when no row points at them.
- **Why:** `sha256` is not unique any more (D-006), so the database cannot catch this race on its own.

## D-019 Deleting files

- **Date:** 2026-09-26 (Phase 2)
- **Decision:** Files can be deleted with `DELETE /files/{id or ref}`, from a Delete button on the Files page that asks for confirmation. Any file can be deleted except while it is `processing` or `ai_processing`. Deleting removes the file row and everything that belongs to it: extraction runs (including AI approval records), receipts, line items and flags. If other files are copies of it, the earliest copy becomes the original and the rest link to that one. The stored bytes are removed only when no remaining file uses them.
- **Why:** Chosen by the user, so test uploads and mistakes can be removed. The plan had no delete, only reject.
- **Changes the plan:** Adds an endpoint to the API table. Deleting a file also deletes its audit trail of AI approvals; rejecting a file keeps it.

## D-020 Synthetic samples until real ones arrive

- **Date:** 2026-09-26 (Phase 3)
- **Decision:** Phase 3 is built and tested against generated receipts in varied formats: Indian GST tax invoices, retail and fuel receipts, rupee symbols, Indian digit grouping, several date styles, single-sheet and multi-sheet workbooks, CSVs with different delimiters and encodings, one-page, multi-page and multi-receipt PDFs. `backend/scripts/make_samples.py` writes them, with their expected answers, to `data/samples/synthetic/` so they can also be uploaded by hand. The rules will be tuned on the user's real samples when they arrive.
- **Why:** Chosen by the user. No real samples exist yet.

## D-021 Spreadsheet layout: one receipt per sheet

- **Date:** 2026-09-26 (Phase 3)
- **Decision:** The Excel/CSV extractor reads form-style invoices: label and value cells (for example `Invoice No:` then `INV-0421`, beside or below the label) plus an items table, one receipt per sheet. A CSV is one sheet. Sheets with no recognisable receipt, such as notes, are skipped. Expense logs with one row per receipt, or one row per line item, are not recognised in this phase and go to `needs_review`.
- **Why:** Chosen by the user.

## D-022 Splitting multi-page PDFs by content

- **Date:** 2026-09-26 (Phase 3)
- **Decision:** In a text PDF, a page starts a new receipt when it carries its own header: a bill or invoice number, or a document title such as "Tax Invoice" or "Receipt" near the top. Pages without one continue the previous receipt. A one-page PDF is one receipt.
- **Why:** Chosen by the user. A two-page invoice stays whole, and a PDF of several bills is split.

## D-023 xlrd for legacy .xls files

- **Date:** 2026-09-26 (Phase 3)
- **Decision:** Add `xlrd` to read `.xls` files. `pandas` and `openpyxl` (for `.xlsx`) and `pdfplumber` (for text PDFs) come from the planned stack.
- **Why:** Chosen by the user. `.xls` is accepted at upload (D-016) and should work end to end.

## D-024 Phase 3 extraction rules

- **Date:** 2026-09-26 (Phase 3)
- **Decision:**
  1. Dates are read day-first (`03/04/2026` is 3 April), as in India. ISO dates (`2026-04-03`) and month names are also understood.
  2. Until Phase 4 brings full validation, a file is `parsed` when every receipt in it has a vendor, a date and a total, and its confidence meets the threshold for its file type (set in config). Otherwise it goes to `needs_review`, and its result is kept on the extraction run.
  3. A vendor's normalized name starts as the printed name with spacing and stray punctuation tidied. Merging different spellings of one vendor comes later.
  4. Scanned PDFs and images are detected but not read until Phase 5. They wait in `needs_review` with a note, and no extraction run is recorded, so Phase 5 can still record their one library run.
  5. A file whose bytes cannot be opened (corrupt, password-protected or empty) is `flagged` with an `unreadable` flag and never retried.
  6. PyMuPDF is not used in Phase 3. It is licensed under the AGPL, which matters if Parchi is ever distributed as closed source. The choice of page renderer is revisited in Phase 5.
- **Why:** Sensible defaults recorded here so they can be revisited when real samples arrive.

## D-025 Background worker and recovery

- **Date:** 2026-09-26 (Phase 3)
- **Decision:** An ARQ worker on Redis processes files. The API queues a job after a file is registered; the job id is `process-<file id>`, so the same file is never queued twice. A worker claims a file by moving it from `pending` (or `failed`) to `processing` in one statement, so two workers cannot take the same file. A job times out after 5 minutes. Every minute a recovery task re-queues `pending` files, puts files stuck in `processing` for over 10 minutes back to `pending`, and retries `failed` files with backoff, up to 3 attempts. If Redis is down at upload time, the file stays `pending` and recovery queues it later.
- **Why:** Hard rule 5 needs a recovery job, and it costs little to have it from the start.

## D-026 User-managed categories

- **Date:** 2026-09-26 (between Phases 3 and 4)
- **Decision:** Categories move from a fixed list in code to a `categories` table. It starts with the eight built-in categories from D-009 (Fuel, Travel, Food, Office, Utilities, Maintenance, Services, Other), and people can add their own. Names are unique regardless of capitalisation and spacing, up to 50 characters. Built-in categories cannot be renamed or deleted. A custom category can be renamed, and deleted only while no receipt or vendor uses it. Receipts store `category_auto_id` and `category_override_id` with a generated `category_id` (the override if set, otherwise the automatic one); vendors store `default_category_id`. The API gains `GET/POST /categories` and `PATCH/DELETE /categories/{id}`. The UI for choosing and adding categories arrives with the Review page in Phase 4.
- **Why:** Chosen by the user: a managed list rather than free text per receipt, so the same category is not counted twice because of a typo.
- **Changes:** D-009's fixed list, and the category columns from D-003 and D-012.

## D-027 Lessons from the first real receipt

- **Date:** 2026-09-26 (Phase 3)
- **Decision:** The first real sample, a two-invoice marketplace PDF, changed four reading rules:
  1. A number followed by `%`, even after a space (`9.0 %`), is a rate and never an amount.
  2. Items tables printed as plain text, without ruled lines, are read: the header row names the numeric columns in order, a row is an item when it ends with that many numbers, and the table's Total row supplies the taxable value (subtotal) and the tax (SGST + CGST + IGST ...) when those are not printed on their own lines.
  3. Date labels are tried strongest first: "Invoice Date" wins over "Order Date" or a plain "Date".
  4. A vendor name that differs from an existing one only in capitalisation gets the same normalized name (it keeps its own raw name), so the two group together (refines D-024 item 3).
- **Why:** The first version read the GST rate as the tax amount and found no line items on this layout, which is common for marketplace and billing-software invoices. A synthetic sample with the same layout (`marketplace_invoices.pdf`) keeps it tested without committing the real receipt.

## D-028 Query page dates: pickers, defaulting to this financial year

- **Date:** 2026-09-26 (recorded ahead of Phase 7)
- **Decision:** The Query page's **From** and **To** filters are date pickers, not text boxes. They open on the current Indian financial year to date: From is 1 April of the current financial year and To is today, in `APP_TIMEZONE`. Before 1 April, that is 1 April of the previous calendar year. Changing either date re-runs the filters. From cannot be later than To. A plain-English question that names a period ("fuel in August") uses that period instead, and the page shows the range it used.
- **Why:** Chosen by the user. The financial year is the period expenses are usually totalled and filed for.

## D-029 Phase 4 validation rules

- **Date:** 2026-09-26 (Phase 4)
- **Decision:**
  1. **Arithmetic:** amounts may be off by up to ₹1, which also covers the "Round Off" line Indian bills use to reach a whole rupee. Line items must add up to the subtotal or to the total. Subtotal + tax must equal the total when both are printed.
  2. **Dates:** plausible from 1 April of the previous financial year up to today, in `APP_TIMEZONE`. A future date, or anything older, fails.
  3. **Duplicate receipts:** a receipt matches one already stored (on a `parsed` or `resolved` file) when the vendor's normalized name (ignoring case), the receipt number and the total are the same. Without a receipt number, vendor, date and total are used.
  4. **A failed check does not stop a file (user's choice).** Its receipts are stored and count in queries, the file stays `parsed`, and each problem is recorded as an open warning flag: `arithmetic_mismatch`, `validation_failed` for dates, or `duplicate_receipt`. Only missing required fields (vendor, date, total), low confidence or no receipt at all still send a file to `needs_review` (D-024), because such a receipt cannot be stored.
- **Why:** Chosen by the user. Checked data counts at once, and warnings stay visible until a person looks at them.
- **Changes the plan:** `parsed` no longer means every check passed. It means the receipts are stored, and the file may have open warning flags.

## D-030 Review, resolving and rejecting

- **Date:** 2026-09-26 (Phase 4)
- **Decision:**
  1. The Review page shows one file: a preview of the original (PDFs inline; spreadsheets and other types as a download), its reference number, its open flags, and each receipt's fields and line items, all editable, including the category (built-in or a new custom one, D-026).
  2. **Save** records the edits as a `manual` extraction run. That run becomes the accepted one, the file's receipts are replaced with the edited ones (D-013 item 5), the checks run again on the edited values, and the file becomes `resolved`. Warnings still left after the edit are marked resolved by the local user, since the person has seen them and decided.
  3. **Mark as OK** resolves a single warning flag without editing.
  4. **Reject** marks a file `rejected` (not a receipt, or a bad scan), with the reason kept in `error`. Its receipts are removed from queries.
  5. The Review queue lists files in `needs_review` or `flagged`, and `parsed` files with open warning flags.
- **Why:** Plan phase 4, with D-029's warning flags.

## D-031 Error report as PDF

- **Date:** 2026-09-26 (Phase 4)
- **Decision:** `GET /files/{id}/error-report` returns a PDF: reference number, file details, open and resolved flags, every extraction run with its result and error, and the `run_id` needed to find the log lines. `GET /files/error-reports.zip` holds the originals of all files with problems plus one combined PDF. The PDF is written with ReportLab, which is BSD-licensed. Amounts are printed with "Rs." because the standard PDF fonts have no rupee symbol.
- **Why:** Chosen by the user, as easy to email or print. ReportLab over PyMuPDF because of the AGPL (D-024 item 6).
