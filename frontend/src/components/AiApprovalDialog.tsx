import { useEffect, useId, useRef, useState } from "react";

import { useAiUsage, useApproveAi, type AiProvider, type FileSummary } from "@/api/queries";
import { extensionLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

type Candidate = Pick<FileSummary, "ref_no" | "original_name" | "kind">;

const PROVIDER_COMPANY: Record<AiProvider, string> = { anthropic: "Anthropic", openai: "OpenAI" };

function sentAs(file: Candidate): string {
  return file.kind === "excel" || file.kind === "csv" ? "as text" : "as it is";
}

/**
 * The approval dialog (designs AiConfirmC and AiBatchC). Nothing is sent until the person
 * ticks the approval and presses Approve and extract; the server checks the approval again.
 */
export function AiApprovalDialog({
  files,
  onClose,
  onApproved,
}: {
  files: Candidate[];
  onClose: () => void;
  onApproved?: () => void;
}) {
  const titleId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);
  const { data: usage } = useAiUsage();
  const approve = useApproveAi();
  const configured = usage?.providers.filter((p) => p.configured) ?? [];
  const [provider, setProvider] = useState<AiProvider | null>(null);
  const [agreed, setAgreed] = useState(false);
  const chosen = provider ?? configured[0]?.provider ?? null;
  const count = files.length;
  const one = count === 1 ? files[0] : undefined;
  const remaining = usage?.remaining ?? 0;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    return () => opener?.focus();
  }, []);

  let blocked: string | null = null;
  if (usage && !usage.enabled) {
    blocked = "AI is switched off. Set AI_ENABLED=true in .env to allow approved reads.";
  } else if (usage && configured.length === 0) {
    blocked = "No AI provider has an API key yet. Add ANTHROPIC_API_KEY or OPENAI_API_KEY to .env.";
  } else if (usage && remaining < count) {
    blocked = `Today's limit allows ${remaining} more AI ${remaining === 1 ? "read" : "reads"}.`;
  }
  const canApprove = !blocked && agreed && chosen !== null && !approve.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onKeyDown={(event) => {
        if (event.key === "Escape" && !approve.isPending) onClose();
        if (event.key === "Tab") {
          // Keep focus inside the dialog.
          const focusable = Array.from(
            event.currentTarget.querySelectorAll<HTMLElement>(
              "button:not(:disabled), input:not(:disabled)",
            ),
          );
          const first = focusable[0];
          const last = focusable.at(-1);
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex max-h-[90vh] w-full max-w-lg flex-col gap-5 overflow-y-auto rounded-2xl border border-border bg-card p-6 shadow-[0_8px_24px_rgba(0,0,0,0.35)]"
      >
        <div>
          <h2 id={titleId} className="font-heading text-xl font-semibold">
            {one ? "Extract this file with AI?" : `Extract ${count} files with AI?`}
          </h2>
          <p className="mt-1 text-sm text-muted">
            {one
              ? "The library result failed its checks. AI can try again, but only if you approve it."
              : "One approval covers every file listed here. Files you did not select are not sent."}
          </p>
        </div>

        <ul className="flex max-h-40 flex-col gap-2 overflow-y-auto">
          {files.map((file) => (
            <li key={file.ref_no} className="flex items-center gap-3">
              <span className="inline-flex h-7 w-12 shrink-0 items-center justify-center rounded-md bg-divider font-mono text-[11px] text-pending">
                {extensionLabel(file.original_name)}
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="truncate font-mono text-sm">{file.original_name}</span>
                <span className="font-mono text-xs text-muted">{file.ref_no}</span>
              </span>
            </li>
          ))}
        </ul>

        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-sm font-semibold">Choose a provider</legend>
          <div className="flex gap-3">
            {(usage?.providers ?? []).map((option) => (
              <label
                key={option.provider}
                className={cn(
                  "flex min-h-16 flex-1 cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-3",
                  chosen === option.provider ? "border-accent bg-accent-soft/60" : "border-input",
                  !option.configured && "cursor-not-allowed opacity-50",
                )}
              >
                <input
                  type="radio"
                  name="provider"
                  value={option.provider}
                  checked={chosen === option.provider}
                  disabled={!option.configured}
                  onChange={() => setProvider(option.provider)}
                  className="size-4.5 accent-accent"
                />
                <span className="flex flex-col">
                  <span className="font-semibold">{option.label}</span>
                  <span className="text-[13px] text-muted">
                    {option.configured
                      ? `${PROVIDER_COMPANY[option.provider]} · ${option.model}`
                      : "No API key set"}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="flex flex-col gap-1.5 rounded-xl border border-border bg-sidebar px-4 py-3.5 text-sm">
          <span className="font-semibold">What gets sent</span>
          <span className="text-muted">
            {one
              ? `The original file, ${one.original_name}, goes ${sentAs(one)} to the provider you choose.`
              : `The ${count} original files listed above go to the provider you choose (spreadsheets as text).`}
          </span>
          <span className="text-muted">Nothing is sent until you press Approve and extract.</span>
          <span className="text-muted">
            {one
              ? "The result is saved as a new run, so the library result is kept."
              : "Each result is saved as a new run, so the library results are kept."}
          </span>
        </div>

        <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(event) => setAgreed(event.target.checked)}
            disabled={Boolean(blocked)}
            className="size-5 accent-accent"
          />
          {one
            ? "I approve sending this file to the selected provider."
            : `I approve sending these ${count} files to the selected provider.`}
        </label>

        {usage && !blocked && (
          <p className="-mt-2 text-[13px] text-muted">
            Uses {count} of your {remaining} remaining approvals today.
          </p>
        )}
        {blocked && (
          <p role="alert" className="text-sm text-review">
            {blocked}
          </p>
        )}
        {approve.error instanceof Error && (
          <p role="alert" className="text-sm text-flagged">
            {approve.error.message}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onClose}
            disabled={approve.isPending}
            className="h-11 rounded-[10px] border border-input bg-raised px-4 text-sm font-medium disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canApprove}
            onClick={() =>
              chosen &&
              approve.mutate(
                { refs: files.map((f) => f.ref_no), provider: chosen },
                {
                  onSuccess: () => {
                    onApproved?.();
                    onClose();
                  },
                },
              )
            }
            className="h-11 rounded-[10px] bg-accent px-5 text-sm font-semibold text-on-accent disabled:opacity-50"
          >
            {approve.isPending ? "Sending…" : "Approve and extract"}
          </button>
        </div>
        <p className="-mt-2 text-center text-xs text-muted">
          Your approval is recorded with your name, the time and the provider.
        </p>
      </div>
    </div>
  );
}
