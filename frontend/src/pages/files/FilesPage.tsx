import { createColumnHelper, flexRender, tableFeatures, useTable } from "@tanstack/react-table";
import { ChevronLeft, ChevronRight, Download } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { downloadUrl, useFiles, type FileStatus, type FileSummary } from "@/api/queries";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { extensionLabel, formatUploaded } from "@/lib/format";
import { STATUS_LABELS } from "@/lib/status";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

// Chip order from the design. Counts per chip arrive with GET /files/summary in phase 4.
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

const COLUMNS = column.columns([
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
          {file.error && <span className="text-[13px] text-flagged">{file.error}</span>}
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
        <a
          href={downloadUrl(file)}
          download
          className="inline-flex h-11 items-center gap-2 rounded-[10px] border border-input bg-raised px-3.5 text-sm font-medium"
          aria-label={`Download ${file.original_name}`}
        >
          <Download size={18} strokeWidth={1.8} aria-hidden="true" />
          File
        </a>
      </div>
    ),
  }),
]);

const GRID = "grid grid-cols-[minmax(0,1fr)_140px_140px_160px] gap-x-4 px-6";

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

  const table = useTable({
    features,
    data: data?.items ?? [],
    columns: COLUMNS,
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
      <PageHeader eyebrow="Status" title="Files" />

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
    </>
  );
}
