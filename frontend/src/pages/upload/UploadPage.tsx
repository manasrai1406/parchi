import { UploadCloud } from "lucide-react";
import { useDropzone } from "react-dropzone";
import { Link } from "react-router";

import { IN_PROGRESS, useBatches, type FileSummary } from "@/api/queries";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useUploadSession, type UploadItem } from "./useUploadSession";

// Mirrors the server's rules (D-016). The server still enforces them.
const MAX_BYTES = 20 * 1024 * 1024;
const ACCEPT = {
  "application/pdf": [".pdf"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/png": [".png"],
  "image/webp": [".webp"],
  "image/heic": [".heic"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "application/vnd.ms-excel": [".xls"],
  "text/csv": [".csv"],
};

const STEPS = [
  {
    title: "Register",
    text: "The file is hashed, stored and given a reference number. If the same file was uploaded before, you choose whether to keep a copy.",
  },
  {
    title: "Extract with libraries",
    text: "pdfplumber, pandas or OCR read the vendor, date, items and totals.",
  },
  {
    title: "Validate",
    text: "Line items must add up, dates must be plausible, and repeated receipts are caught.",
  },
  {
    title: "AI only if you approve",
    text: "Files that fail checks wait in Needs review. Nothing is sent to Claude or OpenAI until you approve it.",
  },
];

function ProgressBar({ fraction, tone }: { fraction: number; tone: "active" | "queued" | "done" }) {
  return (
    <div className="h-1.5 rounded-full bg-track">
      <div
        className={cn(
          "h-1.5 rounded-full transition-[width]",
          tone === "active" && "bg-processing",
          tone === "queued" && "bg-queued",
          tone === "done" && "bg-success",
        )}
        style={{ width: `${Math.max(4, Math.round(fraction * 100))}%` }}
      />
    </div>
  );
}

function ServerState({ file }: { file: FileSummary }) {
  if (file.status === "pending") {
    return (
      <div className="flex flex-col gap-2">
        <ProgressBar fraction={0.04} tone="queued" />
        <span className="text-[13px] font-semibold text-pending">Queued</span>
      </div>
    );
  }
  if (IN_PROGRESS.includes(file.status)) {
    return (
      <div className="flex flex-col gap-2">
        <ProgressBar fraction={0.6} tone="active" />
        <span className="text-[13px] font-semibold text-processing">Processing</span>
      </div>
    );
  }
  if (file.status === "parsed" || file.status === "resolved") {
    return (
      <div className="flex flex-col gap-2">
        <ProgressBar fraction={1} tone="done" />
        <span className="text-[13px] font-semibold text-success-text">Done</span>
      </div>
    );
  }
  return <StatusBadge status={file.status} />;
}

function UploadRow({
  item,
  latest,
  onKeep,
  onSkip,
}: {
  item: UploadItem;
  latest?: FileSummary;
  onKeep: () => void;
  onSkip: () => void;
}) {
  const file = latest ?? item.registered;
  let detail: React.ReactNode = formatBytes(item.file.size);
  let detailTone = "text-muted";
  let state: React.ReactNode = null;

  switch (item.phase) {
    case "waiting":
      state = <span className="text-[13px] font-semibold text-pending">Waiting to upload</span>;
      break;
    case "uploading":
      state = (
        <div className="flex flex-col gap-2">
          <ProgressBar fraction={item.progress} tone="active" />
          <span className="text-[13px] font-semibold text-processing">
            Uploading {Math.round(item.progress * 100)}%
          </span>
        </div>
      );
      break;
    case "registered":
      if (file) {
        detail = (
          <>
            <span className="font-mono">{file.ref_no}</span> · {formatBytes(file.size_bytes)}
            {file.status === "pending" && " · Waiting for a worker"}
            {file.duplicate_of && (
              <>
                {" "}
                · Copy of <span className="font-mono">{file.duplicate_of.ref_no}</span>
              </>
            )}
          </>
        );
        state = <ServerState file={file} />;
      }
      break;
    case "duplicate":
      detailTone = "text-review";
      detail = (
        <>
          Identical to {item.duplicateOf?.original_name} (
          <span className="font-mono">{item.duplicateOf?.ref_no}</span>). Not saved.
        </>
      );
      state = (
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onKeep}
            className="h-11 rounded-[10px] bg-accent px-4 text-sm font-semibold text-on-accent"
          >
            Keep a copy
          </button>
          <button
            type="button"
            onClick={onSkip}
            className="h-11 rounded-[10px] border border-input bg-raised px-4 text-sm font-medium"
          >
            Skip
          </button>
        </div>
      );
      break;
    case "skipped":
      detailTone = "text-muted";
      detail = (
        <>
          Skipped. Same as <span className="font-mono">{item.duplicateOf?.ref_no}</span>.
        </>
      );
      state = <span className="text-[13px] font-semibold text-muted">Skipped</span>;
      break;
    case "error":
      detailTone = "text-flagged";
      detail = item.error;
      state = <span className="text-[13px] font-semibold text-flagged">Not uploaded</span>;
      break;
  }

  return (
    <li className="grid min-h-[72px] grid-cols-[minmax(0,1fr)_260px] items-center gap-x-6 border-b border-divider px-6 py-3.5 last:border-b-0">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate font-mono text-sm font-medium" title={item.file.name}>
          {item.file.name}
        </span>
        <span className={cn("text-[13px]", detailTone)}>{detail}</span>
      </div>
      <div aria-live="polite">{state}</div>
    </li>
  );
}

export function UploadPage() {
  const { items, batchIds, addFiles, keepDuplicate, skipDuplicate } = useUploadSession();
  const batches = useBatches(batchIds);
  const latestById = new Map<number, FileSummary>(
    batches.flatMap((query) => query.data?.files.map((file) => [file.id, file] as const) ?? []),
  );

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop: addFiles,
    accept: ACCEPT,
    maxSize: MAX_BYTES,
    noClick: true,
    noKeyboard: true,
  });

  return (
    <>
      <div>
        <PageHeader eyebrow="New batch" title="Upload receipts" />
        <p className="mt-2 text-base text-muted">
          PDFs, photos and spreadsheets. Each file is registered, parsed and checked automatically.
        </p>
      </div>

      <div className="flex items-start gap-6">
        <div className="flex min-w-0 grow flex-col gap-6">
          <div
            {...getRootProps({
              className: cn(
                "flex h-66 flex-col items-center justify-center gap-3.5 rounded-2xl border-2 border-dashed text-center",
                isDragActive
                  ? "border-accent bg-accent-soft/40"
                  : "border-accent-border bg-sidebar",
              ),
            })}
          >
            <input {...getInputProps({ "aria-label": "Choose files to upload" })} />
            <div className="flex size-14 items-center justify-center rounded-full bg-accent-soft text-accent-text">
              <UploadCloud size={26} aria-hidden="true" />
            </div>
            <div className="font-heading text-xl font-semibold">
              {isDragActive ? "Drop to upload" : "Drag files here"}
            </div>
            <div className="flex items-center gap-3 text-sm text-muted">
              <span>or</span>
              <button
                type="button"
                onClick={open}
                className="h-11 rounded-[10px] bg-accent px-5 text-sm font-semibold text-on-accent"
              >
                Browse files
              </button>
            </div>
            <div className="text-[13px] text-muted">
              PDF, JPG, PNG, WEBP, HEIC, XLSX, XLS, CSV. Up to 20 MB per file.
            </div>
          </div>

          {items.length > 0 && (
            <section
              aria-label="This batch"
              className="overflow-hidden rounded-2xl border border-border bg-card shadow-[0_8px_24px_rgba(0,0,0,0.35)]"
            >
              <div className="flex h-14 items-center justify-between border-b border-border px-6">
                <h2 className="font-heading text-[17px] font-semibold">This batch</h2>
                <Link
                  to="/files"
                  className="inline-flex h-11 items-center text-sm font-semibold text-accent-text"
                >
                  View in Files
                </Link>
              </div>
              <ul>
                {items.map((item) => (
                  <UploadRow
                    key={item.key}
                    item={item}
                    latest={item.registered ? latestById.get(item.registered.id) : undefined}
                    onKeep={() => keepDuplicate(item.key)}
                    onSkip={() => skipDuplicate(item.key)}
                  />
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside className="flex w-80 shrink-0 flex-col gap-5 rounded-2xl border border-border bg-card p-6 shadow-[0_8px_24px_rgba(0,0,0,0.35)]">
          <h2 className="font-heading text-lg font-semibold">What happens to a file</h2>
          <ol className="flex flex-col gap-4">
            {STEPS.map((step, index) => (
              <li key={step.title} className="flex gap-3">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-soft font-mono text-[13px] font-semibold text-accent-text">
                  {index + 1}
                </span>
                <div className="flex flex-col gap-1">
                  <span className="text-[15px] font-semibold">{step.title}</span>
                  <span className="text-[13px] text-muted">{step.text}</span>
                </div>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </>
  );
}
