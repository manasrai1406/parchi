import { useState } from "react";

import { useRejectFile, type FileDetail } from "@/api/queries";
import { ConfirmDialog } from "@/components/ConfirmDialog";

const REASONS = ["Not a receipt", "Bad scan or unreadable", "Duplicate of another file"];

export function RejectDialog({ file, onClose }: { file: FileDetail; onClose: () => void }) {
  const reject = useRejectFile(file.ref_no);
  const [reason, setReason] = useState(REASONS[0]!);
  const [other, setOther] = useState("");
  const chosen = reason === "Other" ? other.trim() : reason;

  return (
    <ConfirmDialog
      title={`Reject ${file.original_name}?`}
      confirmLabel="Reject file"
      busyLabel="Rejecting…"
      busy={reject.isPending}
      error={reject.error instanceof Error ? reject.error.message : null}
      onCancel={onClose}
      onConfirm={() => {
        if (chosen) reject.mutate(chosen, { onSuccess: onClose });
      }}
    >
      <p>
        <span className="font-mono text-text">{file.ref_no}</span> is kept, but its receipts no
        longer count in totals or queries. You can still edit and save it later.
      </p>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-text">Reason</legend>
        {[...REASONS, "Other"].map((option) => (
          <label key={option} className="flex min-h-11 items-center gap-3 text-text">
            <input
              type="radio"
              name="reason"
              value={option}
              checked={reason === option}
              onChange={() => setReason(option)}
              className="size-5 accent-accent"
            />
            {option}
          </label>
        ))}
        {reason === "Other" && (
          <input
            className="h-11 rounded-[10px] border border-input bg-sidebar px-3 text-sm text-text"
            value={other}
            onChange={(e) => setOther(e.target.value)}
            maxLength={300}
            aria-label="Other reason"
            placeholder="Why is it rejected?"
          />
        )}
      </fieldset>
    </ConfirmDialog>
  );
}
