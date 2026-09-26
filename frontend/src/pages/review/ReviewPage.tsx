import { ArrowLeft, Download, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useForm, useWatch, type UseFormRegister } from "react-hook-form";
import { Link, useParams } from "react-router";

import type { Schemas } from "@/api/client";
import {
  BUSY,
  downloadUrl,
  useCategories,
  useCreateCategory,
  useFileDetail,
  useResolveFlag,
  useSaveReceipts,
  type FileDetail,
} from "@/api/queries";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDate, formatRupees } from "@/lib/format";
import { FLAG_TITLES } from "@/lib/status";
import { cn } from "@/lib/utils";

import { RejectDialog } from "./RejectDialog";
import {
  EMPTY_ITEM,
  formSchema,
  initialValues,
  itemsAddUp,
  libraryResults,
  toReceiptsIn,
  type FormValues,
} from "./receiptForm";

const INPUT =
  "h-11 w-full min-w-0 rounded-[10px] border border-input bg-sidebar px-3 text-sm text-text placeholder:text-muted aria-[invalid=true]:border-flagged";
const SECONDARY =
  "inline-flex h-11 items-center gap-2 rounded-[10px] border border-input bg-raised px-4 text-sm font-medium";

function Preview({ file }: { file: FileDetail }) {
  const url = downloadUrl(file);
  const inline = file.kind === "pdf_text" || file.kind === "pdf_scan";
  const image = file.kind === "image" && !file.original_name.toLowerCase().endsWith(".heic");
  return (
    <section
      aria-label="Original file"
      className="flex min-h-[640px] flex-col overflow-hidden rounded-2xl border border-border bg-card"
    >
      <div className="flex h-14 items-center justify-between border-b border-border px-5">
        <h2 className="font-heading text-[17px] font-semibold">Original file</h2>
        <a href={url} download className={SECONDARY}>
          <Download size={18} strokeWidth={1.8} aria-hidden="true" />
          Download
        </a>
      </div>
      {inline ? (
        <iframe
          title={`Preview of ${file.original_name}`}
          src={`${url}?inline=true`}
          className="grow bg-white"
        />
      ) : image ? (
        <img
          src={`${url}?inline=true`}
          alt={`Receipt ${file.ref_no}`}
          className="m-auto max-h-[800px] object-contain p-4"
        />
      ) : (
        <p className="m-auto max-w-xs p-6 text-center text-sm text-muted">
          Spreadsheets and HEIC photos can't be shown here. Download the file to compare it with the
          values on the right.
        </p>
      )}
    </section>
  );
}

function Flags({ file }: { file: FileDetail }) {
  const resolve = useResolveFlag();
  const open = file.flags.filter((flag) => !flag.resolved);
  if (open.length === 0) return null;
  return (
    <ul className="flex flex-col gap-3" aria-label="Problems">
      {open.map((flag) => {
        const receipt = file.receipts.find((r) => r.id === flag.receipt_id);
        const error = flag.severity === "error";
        return (
          <li
            key={flag.id}
            className={cn(
              "flex items-start justify-between gap-4 rounded-xl border px-4 py-3.5",
              error ? "border-flagged/40 bg-flagged-bg" : "border-review/40 bg-review-bg",
            )}
          >
            <div className="flex flex-col gap-1">
              <span className={cn("text-sm font-semibold", error ? "text-flagged" : "text-review")}>
                {FLAG_TITLES[flag.type] ?? flag.type}
                {receipt && file.receipts.length > 1 && (
                  <span className="ml-2 font-mono text-xs font-normal">{receipt.ref_no}</span>
                )}
              </span>
              <span className="text-[13px] text-text">{flag.detail}</span>
            </div>
            {flag.severity !== "error" && (
              <button
                type="button"
                className={cn(SECONDARY, "shrink-0")}
                disabled={resolve.isPending}
                onClick={() => resolve.mutate(flag.id)}
              >
                Mark as OK
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function CategorySelect({
  index,
  register,
  onCreated,
}: {
  index: number;
  register: UseFormRegister<FormValues>;
  onCreated: (id: number) => void;
}) {
  const { data: categories } = useCategories();
  const create = useCreateCategory();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");

  if (adding) {
    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex gap-2">
          <input
            className={INPUT}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New category name"
            aria-label="New category name"
            maxLength={50}
            autoFocus
          />
          <button
            type="button"
            className={cn(SECONDARY, "shrink-0")}
            disabled={!name.trim() || create.isPending}
            onClick={() =>
              create.mutate(name, {
                onSuccess: (category) => {
                  onCreated(category.id);
                  setAdding(false);
                  setName("");
                },
              })
            }
          >
            Add
          </button>
          <button
            type="button"
            className={cn(SECONDARY, "shrink-0")}
            onClick={() => setAdding(false)}
          >
            Cancel
          </button>
        </div>
        {create.error instanceof Error && (
          <span className="text-xs text-flagged">{create.error.message}</span>
        )}
      </div>
    );
  }
  return (
    <div className="flex gap-2">
      <select
        className={INPUT}
        aria-label="Category"
        {...register(`receipts.${index}.category_id`)}
      >
        <option value="">No category</option>
        {categories?.map((category) => (
          <option key={category.id} value={category.id}>
            {category.name}
          </option>
        ))}
      </select>
      <button type="button" className={cn(SECONDARY, "shrink-0")} onClick={() => setAdding(true)}>
        <Plus size={16} aria-hidden="true" />
        New
      </button>
    </div>
  );
}

type Extracted = Schemas["ReceiptSchema"] | undefined;

const FIELDS: {
  name: "vendor" | "receipt_number" | "receipt_date" | "subtotal" | "tax" | "total";
  label: string;
  type: "text" | "date" | "money";
  show: (r: NonNullable<Extracted>) => string;
}[] = [
  { name: "vendor", label: "Vendor", type: "text", show: (r) => r.vendor ?? "—" },
  {
    name: "receipt_number",
    label: "Receipt no.",
    type: "text",
    show: (r) => r.receipt_number ?? "—",
  },
  { name: "receipt_date", label: "Date", type: "date", show: (r) => formatDate(r.receipt_date) },
  { name: "subtotal", label: "Subtotal", type: "money", show: (r) => formatRupees(r.subtotal) },
  { name: "tax", label: "Tax", type: "money", show: (r) => formatRupees(r.tax) },
  { name: "total", label: "Total", type: "money", show: (r) => formatRupees(r.total) },
];

function ReceiptEditor({
  index,
  library,
  form,
}: {
  index: number;
  library: Extracted;
  form: ReturnType<typeof useForm<FormValues>>;
}) {
  const { register, control, setValue, formState } = form;
  const items = useFieldArray({ control, name: `receipts.${index}.line_items` });
  const receipt = useWatch({ control, name: `receipts.${index}` });
  const errors = formState.errors.receipts?.[index];
  const addUp = receipt ? itemsAddUp(receipt) : null;

  return (
    <div className="flex flex-col gap-5">
      <div className="overflow-hidden rounded-2xl border border-border bg-card">
        <div className="grid grid-cols-[120px_minmax(0,1fr)_minmax(0,1.3fr)] gap-x-4 border-b border-border bg-sidebar px-5 py-2.5 text-xs font-semibold tracking-[0.08em] text-muted uppercase">
          <span>Field</span>
          <span>Library result</span>
          <span>Final value</span>
        </div>
        {FIELDS.map((field) => {
          const error = errors?.[field.name]?.message;
          return (
            <div
              key={field.name}
              className="grid grid-cols-[120px_minmax(0,1fr)_minmax(0,1.3fr)] items-center gap-x-4 border-t border-divider px-5 py-2.5 first-of-type:border-t-0"
            >
              <label htmlFor={`r${index}-${field.name}`} className="text-sm font-medium">
                {field.label}
              </label>
              <span
                className={cn("truncate text-sm text-muted", field.type !== "text" && "font-mono")}
              >
                {library ? field.show(library) : "—"}
              </span>
              <div className="flex flex-col gap-1">
                <input
                  id={`r${index}-${field.name}`}
                  type={field.type === "date" ? "date" : "text"}
                  inputMode={field.type === "money" ? "decimal" : undefined}
                  className={cn(INPUT, field.type !== "text" && "font-mono")}
                  aria-invalid={error ? true : undefined}
                  {...register(`receipts.${index}.${field.name}`)}
                />
                {error && <span className="text-xs text-flagged">{error}</span>}
              </div>
            </div>
          );
        })}
        <div className="grid grid-cols-[120px_minmax(0,1fr)_minmax(0,1.3fr)] items-center gap-x-4 border-t border-divider px-5 py-2.5">
          <span className="text-sm font-medium">Category</span>
          <span className="text-sm text-muted">—</span>
          <CategorySelect
            index={index}
            register={register}
            onCreated={(id) => setValue(`receipts.${index}.category_id`, String(id))}
          />
        </div>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border bg-card">
        <div className="flex h-14 items-center justify-between border-b border-border px-5">
          <h3 className="font-heading text-[17px] font-semibold">Line items</h3>
          {addUp && (
            <span
              className={cn(
                "text-[13px] font-medium",
                addUp.ok ? "text-success-text" : "text-review",
              )}
            >
              {addUp.ok
                ? "Items add up to the total"
                : `Items add up to ${formatRupees(addUp.sum)}`}
            </span>
          )}
        </div>
        {items.fields.length > 0 && (
          <div className="grid grid-cols-[minmax(0,1fr)_80px_110px_120px_44px] gap-x-3 px-5 pt-3 text-xs font-semibold tracking-[0.08em] text-muted uppercase">
            <span>Description</span>
            <span>Qty</span>
            <span>Unit price</span>
            <span>Amount</span>
            <span />
          </div>
        )}
        <ul className="flex flex-col gap-2 px-5 py-3">
          {items.fields.map((item, position) => {
            const itemErrors = errors?.line_items?.[position];
            return (
              <li
                key={item.id}
                className="grid grid-cols-[minmax(0,1fr)_80px_110px_120px_44px] items-start gap-x-3"
              >
                <input
                  className={INPUT}
                  aria-label={`Item ${position + 1} description`}
                  aria-invalid={itemErrors?.description ? true : undefined}
                  {...register(`receipts.${index}.line_items.${position}.description`)}
                />
                <input
                  className={cn(INPUT, "font-mono")}
                  inputMode="decimal"
                  aria-label={`Item ${position + 1} quantity`}
                  aria-invalid={itemErrors?.quantity ? true : undefined}
                  {...register(`receipts.${index}.line_items.${position}.quantity`)}
                />
                <input
                  className={cn(INPUT, "font-mono")}
                  inputMode="decimal"
                  aria-label={`Item ${position + 1} unit price`}
                  aria-invalid={itemErrors?.unit_price ? true : undefined}
                  {...register(`receipts.${index}.line_items.${position}.unit_price`)}
                />
                <input
                  className={cn(INPUT, "font-mono")}
                  inputMode="decimal"
                  aria-label={`Item ${position + 1} amount`}
                  aria-invalid={itemErrors?.amount ? true : undefined}
                  {...register(`receipts.${index}.line_items.${position}.amount`)}
                />
                <button
                  type="button"
                  className="inline-flex size-11 items-center justify-center rounded-[10px] border border-input bg-raised text-flagged"
                  aria-label={`Remove item ${position + 1}`}
                  onClick={() => items.remove(position)}
                >
                  <Trash2 size={16} aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
        <div className="px-5 pb-4">
          <button
            type="button"
            className={SECONDARY}
            onClick={() => items.append({ ...EMPTY_ITEM })}
          >
            <Plus size={16} aria-hidden="true" />
            Add item
          </button>
        </div>
      </div>
    </div>
  );
}

function ReviewForm({ file }: { file: FileDetail }) {
  const form = useForm<FormValues>({ defaultValues: initialValues(file) });
  const receipts = useFieldArray({ control: form.control, name: "receipts" });
  const library = libraryResults(file);
  const [current, setCurrent] = useState(0);
  const [rejecting, setRejecting] = useState(false);
  const save = useSaveReceipts(file.ref_no);
  const [saved, setSaved] = useState(false);
  const busy = BUSY.includes(file.status) || file.status === "pending";

  const onSubmit = form.handleSubmit((values) => {
    setSaved(false);
    const checked = formSchema.safeParse(values);
    if (!checked.success) {
      for (const issue of checked.error.issues) {
        form.setError(issue.path.join(".") as never, { message: issue.message });
      }
      const first = checked.error.issues[0]?.path[1];
      if (typeof first === "number") setCurrent(first);
      return;
    }
    save.mutate(toReceiptsIn(values), {
      onSuccess: (detail) => {
        form.reset(initialValues(detail));
        setSaved(true);
      },
    });
  });

  return (
    <>
      <form onSubmit={onSubmit} noValidate className="flex min-w-0 flex-col gap-5">
        <Flags file={file} />

        {receipts.fields.length > 1 && (
          <div role="tablist" aria-label="Receipts in this file" className="flex flex-wrap gap-2">
            {receipts.fields.map((field, index) => (
              <button
                key={field.id}
                type="button"
                role="tab"
                aria-selected={current === index}
                onClick={() => setCurrent(index)}
                className={cn(
                  "inline-flex h-11 items-center rounded-full border px-4 text-sm font-medium",
                  current === index
                    ? "border-accent bg-accent text-on-accent"
                    : "border-input bg-card",
                  form.formState.errors.receipts?.[index] && "border-flagged",
                )}
              >
                Receipt {index + 1}
              </button>
            ))}
          </div>
        )}

        {receipts.fields.map((field, index) =>
          index === current ? (
            <ReceiptEditor key={field.id} index={index} library={library[index]} form={form} />
          ) : null,
        )}

        {save.error instanceof Error && (
          <p role="alert" className="text-sm text-flagged">
            {save.error.message}
          </p>
        )}
        {saved && (
          <p role="status" className="text-sm text-success-text">
            Saved. The file is resolved.
          </p>
        )}

        <div className="flex items-center justify-end gap-3">
          <button
            type="button"
            className={cn(SECONDARY, "text-flagged")}
            disabled={busy}
            onClick={() => setRejecting(true)}
          >
            Reject file
          </button>
          <button
            type="submit"
            disabled={busy || save.isPending}
            className="h-11 rounded-[10px] bg-accent px-5 text-sm font-semibold text-on-accent disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Accept and resolve"}
          </button>
        </div>
        {busy && (
          <p className="text-right text-[13px] text-muted">
            This file is still being read. It can be reviewed when it finishes.
          </p>
        )}
      </form>
      {/* Outside the form, so Enter in the dialog does not submit the review. */}
      {rejecting && <RejectDialog file={file} onClose={() => setRejecting(false)} />}
    </>
  );
}

export function ReviewPage() {
  const { ref = "" } = useParams();
  const { data: file, isPending, isError, error } = useFileDetail(ref);

  return (
    <>
      <Link
        to="/files"
        className="inline-flex h-11 items-center gap-2 self-start text-sm font-semibold text-accent-text"
      >
        <ArrowLeft size={18} aria-hidden="true" />
        Back to Files
      </Link>

      {isPending && <p className="text-muted">Loading…</p>}
      {isError && (
        <p className="text-flagged">
          {error instanceof Error ? error.message : "Could not load the file."}
        </p>
      )}

      {file && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="font-heading text-[30px] font-semibold tracking-[-0.02em]">
              {file.original_name}
            </h1>
            <StatusBadge status={file.status} />
            <span className="font-mono text-sm text-muted">{file.ref_no}</span>
          </div>
          {file.error && (
            <p
              className={cn(
                "text-sm",
                file.status === "needs_review" ? "text-review" : "text-flagged",
              )}
            >
              {file.error}
            </p>
          )}
          <div className="grid grid-cols-[minmax(0,5fr)_minmax(0,7fr)] items-start gap-6">
            <Preview file={file} />
            {/* Re-mounted per file, so the form starts from that file's values. */}
            <ReviewForm key={`${file.id}-${file.status}`} file={file} />
          </div>
        </>
      )}
    </>
  );
}
