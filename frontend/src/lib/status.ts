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

export const FLAG_TITLES: Record<string, string> = {
  arithmetic_mismatch: "The numbers don't add up",
  validation_failed: "The date looks wrong",
  duplicate_receipt: "Possible duplicate receipt",
  parser_conflict: "The readers disagree",
  unreadable: "The file can't be read",
};
