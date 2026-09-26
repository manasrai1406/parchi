import { useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Link } from "react-router";

import {
  receiptsCsvUrl,
  receiptsKey,
  useAsk,
  useCategories,
  useReceipts,
  useVendors,
  type AskOut,
  type ReceiptFilters,
  type ReceiptPage,
} from "@/api/queries";
import { PageHeader } from "@/components/PageHeader";
import { formatRupees } from "@/lib/format";
import { cn } from "@/lib/utils";

/** What the filter boxes hold, as typed. Dates apply at once (D-028); the rest on Apply. */
type Draft = { vendor: string; category_id: string; min_total: string; max_total: string };

const EMPTY_DRAFT: Draft = { vendor: "", category_id: "", min_total: "", max_total: "" };
const AMOUNT = /^\d{1,10}(\.\d{1,2})?$/;
const GRID = "grid grid-cols-[110px_minmax(0,1fr)_120px_120px_130px_170px] gap-x-4 px-6";
const FIELD =
  "h-11 min-w-0 rounded-[10px] border border-input bg-sidebar px-3 text-sm text-text placeholder:text-muted";

function draftFrom(filters: ReceiptFilters): Draft {
  return {
    vendor: filters.vendor ?? "",
    category_id: filters.category_id ? String(filters.category_id) : "",
    min_total: filters.min_total ?? "",
    max_total: filters.max_total ?? "",
  };
}

function AskBox({ onAnswer }: { onAnswer: (answer: AskOut) => void }) {
  const [question, setQuestion] = useState("");
  const ask = useAsk();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (question.trim()) ask.mutate(question.trim(), { onSuccess: onAnswer });
  };

  return (
    <>
      <form onSubmit={submit} className="flex gap-3">
        <label htmlFor="ask" className="sr-only">
          Ask about your receipts
        </label>
        <input
          id="ask"
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="e.g. Fuel in August, or food over ₹500 last month"
          maxLength={300}
          className="h-13 min-w-0 flex-1 rounded-[10px] border border-input bg-sidebar px-4 text-base text-text placeholder:text-muted"
        />
        <button
          type="submit"
          disabled={ask.isPending || !question.trim()}
          className="h-13 rounded-[10px] bg-accent px-6 text-[15px] font-semibold text-on-accent disabled:opacity-50"
        >
          {ask.isPending ? "Asking…" : "Ask"}
        </button>
      </form>
      {ask.error instanceof Error && (
        <p role="alert" className="text-sm text-review">
          {ask.error.message}
        </p>
      )}
    </>
  );
}

function Explanation({ answer }: { answer: AskOut }) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2.5 text-sm text-[#B5C4BD]">
        <span className="font-semibold">Understood as</span>
        {answer.understood_as.map((item) => (
          <span
            key={item.label}
            className="rounded-full bg-accent-soft px-3 py-1.25 font-medium text-accent-text"
          >
            {item.label === "Dates" ? item.value : `${item.label}: ${item.value}`}
          </span>
        ))}
      </div>
      {answer.ignored.length > 0 && (
        <p className="text-sm text-review">
          Not understood, so left out: {answer.ignored.map((word) => `“${word}”`).join(", ")}
        </p>
      )}
      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-semibold tracking-[0.08em] text-muted uppercase">
          Query that ran (read-only access)
        </span>
        <pre className="overflow-x-auto rounded-[10px] border border-border bg-[#070C0A] px-3.5 py-3 font-mono text-xs leading-relaxed text-[#B7E9D0]">
          {answer.sql}
        </pre>
      </div>
    </>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1 rounded-2xl border border-border bg-card px-5 py-4 shadow-[0_8px_24px_rgba(0,0,0,0.35)]">
      <span className="text-xs font-semibold tracking-[0.1em] text-muted uppercase">{label}</span>
      <span className="truncate font-heading text-3xl font-semibold text-accent-text">{value}</span>
    </div>
  );
}

function Summary({ data }: { data: ReceiptPage | undefined }) {
  const waiting = data?.waiting_for_review ?? 0;
  return (
    <section aria-label="Summary" className="flex gap-3.5">
      <Tile label="Receipts" value={data ? String(data.count) : "–"} />
      <Tile label="Total" value={data ? formatRupees(data.sum_total) : "–"} />
      <Tile label="Average" value={data ? formatRupees(data.average_total) : "–"} />
      {waiting > 0 && (
        <div className="flex min-w-0 flex-[1.1] flex-col gap-1 rounded-2xl border border-[#5A4310] bg-[#2B2109] px-5 py-4">
          <span className="text-xs font-semibold tracking-[0.1em] text-[#E8CB8E] uppercase">
            Not included
          </span>
          <span className="text-sm leading-snug font-semibold text-[#FFD98A]">
            {waiting === 1 ? "1 file is" : `${waiting} files are`} waiting for review
          </span>
          <Link
            to="/review"
            className="inline-flex h-8 items-center text-sm font-semibold text-review underline"
          >
            See files needing review
          </Link>
        </div>
      )}
    </section>
  );
}

export function QueryPage() {
  const queryClient = useQueryClient();
  const [applied, setApplied] = useState<ReceiptFilters>({});
  const [page, setPage] = useState(1);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [answer, setAnswer] = useState<AskOut | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const { data, isPending, isError, error } = useReceipts(applied, page);
  const { data: vendors } = useVendors();
  const { data: categories } = useCategories();
  const ids = {
    from: useId(),
    to: useId(),
    vendor: useId(),
    category: useId(),
    min: useId(),
    max: useId(),
  };

  // With no dates chosen, the boxes show the range the server used (D-028).
  const from = applied.date_from ?? data?.date_from ?? "";
  const to = applied.date_to ?? data?.date_to ?? "";

  /** Filters set by hand replace a question's reading, including its order and limit. */
  const apply = (filters: ReceiptFilters) => {
    setApplied(filters);
    setPage(1);
    setAnswer(null);
  };

  const changeDate = (which: "date_from" | "date_to", value: string) => {
    const next = { date_from: from || null, date_to: to || null, [which]: value || null };
    if (next.date_from && next.date_to && next.date_from > next.date_to) {
      setProblem("From cannot be later than To.");
      return;
    }
    setProblem(null);
    apply({ ...applied, sort: undefined, limit: undefined, ...next });
  };

  const submitFilters = (event: FormEvent) => {
    event.preventDefault();
    const min = draft.min_total.replace(/,/g, "").trim();
    const max = draft.max_total.replace(/,/g, "").trim();
    if ((min && !AMOUNT.test(min)) || (max && !AMOUNT.test(max))) {
      setProblem("Enter amounts as numbers, e.g. 500 or 1250.50.");
      return;
    }
    if (min && max && Number(min) > Number(max)) {
      setProblem("The minimum amount cannot be more than the maximum.");
      return;
    }
    setProblem(null);
    apply({
      date_from: applied.date_from,
      date_to: applied.date_to,
      vendor: draft.vendor || null,
      category_id: draft.category_id ? Number(draft.category_id) : null,
      min_total: min || null,
      max_total: max || null,
    });
  };

  const showAnswer = (result: AskOut) => {
    const { date_from, date_to, vendor, category_id, min_total, max_total, sort, limit } =
      result.filters;
    const filters = { date_from, date_to, vendor, category_id, min_total, max_total, sort, limit };
    // The answer already holds the first page; put it where the table looks for it.
    queryClient.setQueryData(receiptsKey(filters, 1), result.result);
    setApplied(filters);
    setPage(1);
    setDraft(draftFrom(filters));
    setProblem(null);
    setAnswer(result);
  };

  const count = data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(count / (data?.page_size ?? 50)));
  const rows = data?.items ?? [];

  return (
    <>
      <div>
        <PageHeader eyebrow="Search" title="Query" />
        <p className="mt-2 text-muted">
          Ask a question in plain English, or narrow the receipts with filters.
        </p>
      </div>

      <section
        aria-label="Ask a question"
        className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-5 shadow-[0_8px_24px_rgba(0,0,0,0.35)]"
      >
        <AskBox onAnswer={showAnswer} />
        {answer && <Explanation answer={answer} />}
      </section>

      <form aria-label="Filters" onSubmit={submitFilters} className="flex items-end gap-3.5">
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <label htmlFor={ids.from} className="text-[13px] font-medium text-[#B5C4BD]">
            From
          </label>
          <input
            id={ids.from}
            type="date"
            value={from}
            max={to || undefined}
            onChange={(event) => changeDate("date_from", event.target.value)}
            className={cn(FIELD, "font-mono")}
          />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <label htmlFor={ids.to} className="text-[13px] font-medium text-[#B5C4BD]">
            To
          </label>
          <input
            id={ids.to}
            type="date"
            value={to}
            min={from || undefined}
            onChange={(event) => changeDate("date_to", event.target.value)}
            className={cn(FIELD, "font-mono")}
          />
        </div>
        <div className="flex min-w-0 flex-[2] flex-col gap-1.5">
          <label htmlFor={ids.vendor} className="text-[13px] font-medium text-[#B5C4BD]">
            Vendor
          </label>
          <select
            id={ids.vendor}
            value={draft.vendor}
            onChange={(event) => setDraft({ ...draft, vendor: event.target.value })}
            className={FIELD}
          >
            <option value="">All vendors</option>
            {vendors?.map((vendor) => (
              <option key={vendor} value={vendor}>
                {vendor}
              </option>
            ))}
          </select>
        </div>
        <div className="flex min-w-0 flex-[1.3] flex-col gap-1.5">
          <label htmlFor={ids.category} className="text-[13px] font-medium text-[#B5C4BD]">
            Category
          </label>
          <select
            id={ids.category}
            value={draft.category_id}
            onChange={(event) => setDraft({ ...draft, category_id: event.target.value })}
            className={FIELD}
          >
            <option value="">All categories</option>
            {categories?.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <label htmlFor={ids.min} className="text-[13px] font-medium text-[#B5C4BD]">
            Min amount
          </label>
          <input
            id={ids.min}
            inputMode="decimal"
            placeholder="0"
            value={draft.min_total}
            onChange={(event) => setDraft({ ...draft, min_total: event.target.value })}
            className={cn(FIELD, "font-mono")}
          />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <label htmlFor={ids.max} className="text-[13px] font-medium text-[#B5C4BD]">
            Max amount
          </label>
          <input
            id={ids.max}
            inputMode="decimal"
            placeholder="No limit"
            value={draft.max_total}
            onChange={(event) => setDraft({ ...draft, max_total: event.target.value })}
            className={cn(FIELD, "font-mono")}
          />
        </div>
        <button
          type="submit"
          className="h-11 rounded-[10px] border border-input bg-raised px-5 text-sm font-medium"
        >
          Apply
        </button>
      </form>
      {problem && (
        <p role="alert" className="-mt-3 text-sm text-flagged">
          {problem}
        </p>
      )}

      <Summary data={data} />

      <section
        aria-label="Results"
        className="overflow-hidden rounded-2xl border border-border bg-card shadow-[0_8px_24px_rgba(0,0,0,0.35)]"
      >
        <div role="table" aria-label="Receipts" aria-rowcount={count}>
          <div
            role="row"
            className={cn(
              GRID,
              "h-10 items-center border-b border-border bg-sidebar text-xs font-semibold tracking-[0.08em] text-muted uppercase",
            )}
          >
            <span role="columnheader">Date</span>
            <span role="columnheader">Vendor</span>
            <span role="columnheader">Receipt no.</span>
            <span role="columnheader">Category</span>
            <span role="columnheader" className="text-right">
              Amount
            </span>
            <span role="columnheader" className="text-right">
              Reference
            </span>
          </div>
          {rows.map((row) => (
            <div
              key={row.ref_no}
              role="row"
              className={cn(
                GRID,
                "h-13 items-center border-t border-divider text-sm first:border-t-0",
              )}
            >
              <span role="cell" className="font-mono text-[13px]">
                {row.receipt_date}
              </span>
              <span role="cell" className="truncate">
                {row.vendor}
              </span>
              <span role="cell" className="truncate font-mono text-[13px]">
                {row.receipt_number ?? "—"}
              </span>
              <span role="cell" className="truncate">
                {row.category ?? "—"}
              </span>
              <span role="cell" className="text-right font-mono text-[13px]">
                {formatRupees(row.total)}
              </span>
              <span role="cell" className="text-right">
                <Link
                  to={`/review/${row.file_ref_no}`}
                  className="inline-flex h-11 items-center font-mono text-xs font-medium text-accent-text"
                >
                  {row.ref_no}
                </Link>
              </span>
            </div>
          ))}
        </div>

        {isPending && <p className="px-6 py-8 text-muted">Loading receipts…</p>}
        {isError && (
          <p role="alert" className="px-6 py-8 text-flagged">
            {error instanceof Error ? error.message : "Could not load receipts."}
          </p>
        )}
        {data && rows.length === 0 && (
          <p className="px-6 py-8 text-muted">No receipts match these filters.</p>
        )}

        <div className="flex h-13 items-center justify-between gap-4 border-t border-border bg-sidebar px-6 text-sm text-muted">
          <span>{count === 1 ? "1 receipt" : `${count} receipts`}</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Previous page"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
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
              onClick={() => setPage(page + 1)}
              className="inline-flex size-11 items-center justify-center rounded-[10px] disabled:opacity-40"
            >
              <ChevronRight size={18} aria-hidden="true" />
            </button>
            <a
              href={receiptsCsvUrl(applied)}
              download
              className="ml-2 inline-flex h-11 items-center gap-2 rounded-[10px] border border-input bg-raised px-4 font-medium text-text"
            >
              <Download size={16} strokeWidth={1.8} aria-hidden="true" />
              Export CSV
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
