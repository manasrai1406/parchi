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
