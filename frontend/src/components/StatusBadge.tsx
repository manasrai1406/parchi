import type { FileStatus } from "@/api/queries";
import { STATUS_LABELS } from "@/lib/status";
import { cn } from "@/lib/utils";

const STYLES: Record<FileStatus, string> = {
  pending: "bg-pending-bg text-pending",
  processing: "bg-processing-bg text-processing",
  parsed: "bg-success-bg text-success-text",
  needs_review: "bg-review-bg text-review",
  ai_processing: "bg-accent-soft text-accent-text",
  flagged: "bg-flagged-bg text-flagged",
  resolved: "border border-resolved-border text-resolved",
  rejected: "border border-input text-muted",
  failed: "bg-flagged-bg text-flagged",
};

/** Never color alone: every badge has a dot and a text label (design rule). */
export function StatusBadge({ status, label }: { status: FileStatus; label?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center gap-2 rounded-full px-3 text-[13px] font-semibold whitespace-nowrap",
        STYLES[status],
      )}
    >
      <span aria-hidden="true" className="size-2 rounded-full bg-current" />
      {label ?? STATUS_LABELS[status]}
    </span>
  );
}
