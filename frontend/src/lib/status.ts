import type { FileStatus } from "@/api/queries";

export const STATUS_LABELS: Record<FileStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  parsed: "Parsed",
  needs_review: "Needs review",
  ai_processing: "AI running",
  flagged: "Flagged",
  resolved: "Resolved",
  rejected: "Rejected",
  failed: "Failed",
};
