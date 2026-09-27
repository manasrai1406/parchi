import { createColumnHelper, flexRender, tableFeatures, useTable } from "@tanstack/react-table";
import { ChevronLeft, ChevronRight, Download, FileWarning, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import {
  ALL_ERROR_REPORTS_URL,
  BUSY,
  downloadUrl,
  errorReportUrl,
  needsAttention,
  useDeleteFile,
  useFiles,
  useSummary,
  type FileStatus,
  type FileSummary,
} from "@/api/queries";
import { can, useCurrentUser } from "@/auth/session";
import { AiApprovalDialog } from "@/components/AiApprovalDialog";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { extensionLabel, formatUploaded } from "@/lib/format";
import { STATUS_LABELS } from "@/lib/status";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

// Chip order from the design, with counts from GET /files/summary.
const CHIPS: (FileStatus | "all")[] = [
  "all",
  "pending",
  "processing",
  "needs_review",
  "flagged",
  "parsed",
  "resolved",
  "rejected",
  "failed",
];

// A plain display table: no sorting or filtering features; the API pages and filters.
const features = tableFeatures({});
const column = createColumnHelper<typeof features, FileSummary>();

// Rows that can be sent to AI together (design: batch selection on the Files page).
const SELECTABLE: readonly FileStatus[] = ["needs_review", "flagged"];

function makeColumns(
  onDelete: (file: FileSummary) => void,
  selected: Map<string, FileSummary>,
  onToggle: (file: FileSummary) => void,
  allowed: { select: boolean; delete: boolean },
) {
  return column.columns([
    column.display({
      id: "select",
      header: () => <span className="sr-only">Select</span>,
      cell: ({ row: { original: file } }) =>
        allowed.select && SELECTABLE.includes(file.status) ? (
          <input
            type="checkbox"
            checked={selected.has(file.ref_no)}
            onChange={() => onToggle(file)}
            aria-label={`Select ${file.original_name}`}
            className="size-5 cursor-pointer accent-accent"
          />
        ) : null,
    }),
    column.display({
      id: "file",
      header: "File",
      cell: ({ row: { original: file } }) => (
        <div className="flex min-w-0 items-center gap-3">
          <span className="inline-flex h-7 w-12 shrink-0 items-center justify-center rounded-md bg-divider font-mono text-[11px] font-medium tracking-[0.04em] text-pending">
            {extensionLabel(file.original_name)}
          </span>
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate font-mono text-sm font-medium" title={file.original_name}>
              {file.original_name}
            </span>
            <span className="font-mono text-xs text-muted">{file.ref_no}</span>
            {file.error && (
              <span
                className={cn(
                  "text-[13px]",
                  file.status === "needs_review" ? "text-review" : "text-flagged",
                )}
              >
                {file.error}
              </span>
            )}
            {!file.error && file.open_flags > 0 && (
              <span className="text-[13px] text-review">
                {file.open_flags === 1
                  ? "1 check to look at"
                  : `${file.open_flags} checks to look at`}
              </span>
            )}
            {file.duplicate_of && (
              <span className="text-[13px] text-muted">
                Copy of <span className="font-mono">{file.duplicate_of.ref_no}</span>
              </span>
            )}
          </div>
        </div>
      ),
    }),
    column.accessor("status", {
      header: "Status",
      cell: (info) => <StatusBadge status={info.getValue()} />,
    }),
    column.accessor("uploaded_at", {
      header: "Uploaded",
      cell: (info) => (
        <span className="text-[13px] text-muted">{formatUploaded(info.getValue())}</span>
      ),
    }),
    column.display({
      id: "actions",
      header: () => <span className="block text-right">Actions</span>,
      cell: ({ row: { original: file } }) => (
        <div className="flex justify-end gap-2">
          {needsAttention(file) && (
            <Link
              to={`/review/${file.ref_no}`}
              className="inline-flex h-11 items-center rounded-[10px] bg-accent px-4 text-sm font-semibold text-on-accent"
              aria-label={`Review ${file.original_name}`}
            >
              Review
            </Link>
          )}
          <a
            href={downloadUrl(file)}
            download
            className="inline-flex h-11 items-center gap-2 rounded-[10px] border border-input bg-raised px-3.5 text-sm font-medium"
            aria-label={`Download ${file.original_name}`}
          >
            <Download size={18} strokeWidth={1.8} aria-hidden="true" />
            File
          </a>
          {needsAttention(file) && (
            <a
              href={errorReportUrl(file)}
              className="inline-flex size-11 items-center justify-center rounded-[10px] border border-input bg-raised"
              aria-label={`Error report for ${file.original_name}`}
              title="Error report (PDF)"
            >
              <FileWarning size={18} strokeWidth={1.8} aria-hidden="true" />
            </a>
          )}
          {allowed.delete && (
            <button
              type="button"
              onClick={() => onDelete(file)}
              disabled={BUSY.includes(file.status)}
              title={
                BUSY.includes(file.status) ? "Cannot delete while it is being processed" : undefined
              }
              aria-label={`Delete ${file.original_name}`}
              className="inline-flex size-11 items-center justify-center rounded-[10px] border border-input bg-raised text-flagged disabled:opacity-40"
            >
              <Trash2 size={18} strokeWidth={1.8} aria-hidden="true" />
            </button>
          )}
        </div>
      ),
    }),
  ]);
}

const GRID = "grid grid-cols-[28px_minmax(0,1fr)_140px_140px_300px] gap-x-4 px-6";

type Summary = NonNullable<ReturnType<typeof useSummary>["data"]>;

function countOf(summary: Summary | undefined, ...statuses: FileStatus[]): number | undefined {
  if (!summary) return undefined;
  return statuses.reduce((sum, status) => sum + (summary.by_status[status] ?? 0), 0);
}

function SummaryCard({
  label,
  count,
  note,
  tone,
}: {
  label: string;
  count: number | undefined;
  note: string;
  tone: string;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1.5 rounded-2xl border border-border bg-card px-5 py-4.5 shadow-[0_8px_24px_rgba(0,0,0,0.35)]">
      <span className="text-xs font-semibold tracking-[0.1em] text-muted uppercase">{label}</span>
      <div className="flex items-baseline gap-3">
        <span className={cn("font-heading text-[40px] leading-none font-semibold", tone)}>
          {count ?? "–"}
        </span>
        <span className="text-sm text-muted">{note}</span>
      </div>
    </div>
  );
}

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

export function FilesPage() {
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") as FileStatus | null) ?? undefined;
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDebounced(search.trim(), 300);

  // Keep the URL in step with the search box, so a filtered view can be shared or reloaded.
  useEffect(() => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (q) next.set("q", q);
        else next.delete("q");
        if (q !== (current.get("q") ?? "")) next.delete("page");
        return next;
      },
      { replace: true },
    );
  }, [q, setParams]);

  const { data, isPending, isError, error } = useFiles({ status, q, page, pageSize: PAGE_SIZE });
  const { data: summary } = useSummary();

  const [toDelete, setToDelete] = useState<FileSummary | null>(null);
  const deletion = useDeleteFile();
  const [selected, setSelected] = useState<Map<string, FileSummary>>(new Map());
  const [approving, setApproving] = useState(false);
  // Reviewers send files to AI; only admins delete (D-044).
  const me = useCurrentUser();
  const allowSelect = can(me, "reviewer");
  const allowDelete = can(me, "admin");
  const columns = useMemo(
    () =>
      makeColumns(
        (file) => {
          deletion.reset();
          setToDelete(file);
        },
        selected,
        (file) =>
          setSelected((current) => {
            const next = new Map(current);
            if (next.has(file.ref_no)) next.delete(file.ref_no);
            else next.set(file.ref_no, file);
            return next;
          }),
        { select: allowSelect, delete: allowDelete },
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset is stable
    [selected, allowSelect, allowDelete],
  );

  const table = useTable({
    features,
    data: data?.items ?? [],
    columns,
    getRowId: (file) => String(file.id),
  });

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const setFilter = (key: string, value: string | null) =>
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set(key, value);
      else next.delete(key);
      if (key !== "page") next.delete("page");
      return next;
    });

  return (
    <>
      <div className="flex items-end justify-between gap-6">
        <PageHeader eyebrow="Status" title="Files" />
        <a
          href={ALL_ERROR_REPORTS_URL}
          className="inline-flex h-11 items-center gap-2 rounded-[10px] border border-input bg-raised px-4.5 text-sm font-medium"
        >
          <Download size={18} strokeWidth={1.8} aria-hidden="true" />
          Download all flagged (.zip)
        </a>
      </div>

      <section aria-label="Summary" className="flex gap-4">
        <SummaryCard
          label="Needs review"
          count={countOf(summary, "needs_review")}
          note="Awaiting a decision"
          tone="text-review"
        />
        <SummaryCard
          label="Flagged"
          count={countOf(summary, "flagged")}
          note="Unreadable or a conflict"
          tone="text-flagged"
        />
        <SummaryCard
          label="Parsed"
          count={countOf(summary, "parsed")}
          note={
            summary?.with_warnings
              ? `${summary.with_warnings} with checks to look at`
              : "Ready to query"
          }
          tone="text-success-text"
        />
        <SummaryCard
          label="In progress"
          count={countOf(summary, "pending", "processing", "ai_processing")}
          note="Queued or running"
          tone="text-processing"
        />
      </section>

      <div className="flex items-center justify-between gap-4">
        <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-2">
          {CHIPS.map((chip) => {
            const pressed = (chip === "all" && !status) || chip === status;
            return (
              <button
                key={chip}
                type="button"
                aria-pressed={pressed}
                onClick={() => setFilter("status", chip === "all" ? null : chip)}
                className={cn(
                  "inline-flex h-11 items-center rounded-full border px-4 text-sm font-medium",
                  pressed
                    ? "border-accent bg-accent text-on-accent"
                    : "border-input bg-card text-text",
                )}
              >
                {chip === "all" ? "All" : STATUS_LABELS[chip]}
                {summary && (
                  <span className="ml-2 font-normal opacity-75">
                    {chip === "all" ? summary.total : countOf(summary, chip)}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search name or reference"
          aria-label="Search name or reference"
          maxLength={100}
          className="h-11 w-60 shrink-0 rounded-[10px] border border-input bg-sidebar px-3.5 text-sm text-text placeholder:text-muted"
        />
      </div>

      <div className="flex flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-[0_8px_24px_rgba(0,0,0,0.35)]">
        {selected.size > 0 && (
          <div
            role="region"
            aria-label="Selection"
            className="flex h-14 items-center justify-between gap-4 border-b border-accent-border bg-accent-soft px-5"
          >
            <span className="text-sm font-semibold text-accent-text">{selected.size} selected</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSelected(new Map())}
                className="h-11 rounded-[10px] border border-accent-border px-4 text-sm font-medium"
              >
                Clear
              </button>
              <button
                type="button"
                onClick={() => setApproving(true)}
                className="h-11 rounded-[10px] bg-accent px-4.5 text-sm font-semibold text-on-accent"
              >
                Extract with AI…
              </button>
            </div>
          </div>
        )}
        <div role="table" aria-label="Files" aria-rowcount={total}>
          {table.getHeaderGroups().map((group) => (
            <div
              key={group.id}
              role="row"
              className={cn(
                GRID,
                "h-10 items-center border-b border-border bg-sidebar text-xs font-semibold tracking-[0.08em] text-muted uppercase",
              )}
            >
              {group.headers.map((header) => (
                <span key={header.id} role="columnheader">
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </span>
              ))}
            </div>
          ))}

          {table.getRowModel().rows.map((row) => (
            <div
              key={row.id}
              role="row"
              className={cn(
                GRID,
                "min-h-16 items-center border-t border-divider py-2.5 first:border-t-0",
              )}
            >
              {row.getAllCells().map((cell) => (
                <div key={cell.id} role="cell" className="min-w-0">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </div>
              ))}
            </div>
          ))}
        </div>

        {isPending && <p className="px-6 py-8 text-muted">Loading files…</p>}
        {isError && (
          <p className="px-6 py-8 text-flagged">
            {error instanceof Error ? error.message : "Could not load files."}
          </p>
        )}
        {data && data.items.length === 0 && (
          <p className="px-6 py-8 text-muted">
            {status || q ? "No files match." : "No files yet. Upload some receipts to start."}
          </p>
        )}

        <div className="flex h-13 items-center justify-between border-t border-border bg-sidebar px-6 text-sm text-muted">
          <span>
            Showing {data?.items.length ?? 0} of {total} files
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Previous page"
              disabled={page <= 1}
              onClick={() => setFilter("page", String(page - 1))}
              className="inline-flex size-11 items-center justify-center rounded-[10px] disabled:opacity-40"
            >
              <ChevronLeft size={18} aria-hidden="true" />
            </button>
            <span>
              {page} / {pages} pages
            </span>
            <button
              type="button"
              aria-label="Next page"
              disabled={page >= pages}
              onClick={() => setFilter("page", String(page + 1))}
              className="inline-flex size-11 items-center justify-center rounded-[10px] disabled:opacity-40"
            >
              <ChevronRight size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      {approving && (
        <AiApprovalDialog
          files={[...selected.values()]}
          onClose={() => setApproving(false)}
          onApproved={() => setSelected(new Map())}
        />
      )}
      {toDelete && (
        <ConfirmDialog
          title={`Delete ${toDelete.original_name}?`}
          confirmLabel="Delete"
          busyLabel="Deleting…"
          busy={deletion.isPending}
          error={deletion.error instanceof Error ? deletion.error.message : null}
          onCancel={() => setToDelete(null)}
          onConfirm={() => deletion.mutate(toDelete, { onSuccess: () => setToDelete(null) })}
        >
          <p>
            <span className="font-mono text-text">{toDelete.ref_no}</span> will be removed with
            everything extracted from it: receipts, checks and its history, including any AI
            approvals.
          </p>
          <p>Copies of this file are kept. This cannot be undone.</p>
        </ConfirmDialog>
      )}
    </>
  );
}
