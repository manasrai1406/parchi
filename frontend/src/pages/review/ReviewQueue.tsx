import { Link } from "react-router";

import { useFiles } from "@/api/queries";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { extensionLabel, formatUploaded } from "@/lib/format";

/** Files a person should look at: needs review, flagged, or parsed with open warnings. */
export function ReviewQueue() {
  const { data, isPending, isError, error } = useFiles({ attention: true, page: 1, pageSize: 100 });

  return (
    <>
      <PageHeader eyebrow="Fix" title="Review" />
      <p className="-mt-2 text-muted">
        Files that failed a check or could not be read. Open one to compare it with what was
        extracted, correct it, and resolve it.
      </p>

      {isPending && <p className="text-muted">Loading…</p>}
      {isError && (
        <p className="text-flagged">{error instanceof Error ? error.message : "Could not load."}</p>
      )}
      {data && data.items.length === 0 && (
        <div className="rounded-2xl border border-border bg-card p-6 text-muted">
          Nothing needs review. New problems appear here as files are processed.
        </div>
      )}
      {data && data.items.length > 0 && (
        <ul className="overflow-hidden rounded-2xl border border-border bg-card">
          {data.items.map((file) => (
            <li key={file.id} className="border-t border-divider first:border-t-0">
              <Link
                to={`/review/${file.ref_no}`}
                className="flex min-h-16 items-center gap-4 px-6 py-3 hover:bg-raised"
              >
                <span className="inline-flex h-7 w-12 shrink-0 items-center justify-center rounded-md bg-divider font-mono text-[11px] font-medium text-pending">
                  {extensionLabel(file.original_name)}
                </span>
                <span className="flex min-w-0 grow flex-col gap-0.5">
                  <span className="truncate font-mono text-sm font-medium">
                    {file.original_name}
                  </span>
                  <span className="truncate text-[13px] text-muted">
                    <span className="font-mono">{file.ref_no}</span>
                    {" · "}
                    {file.error ??
                      (file.open_flags === 1
                        ? "1 check to look at"
                        : `${file.open_flags} checks to look at`)}
                  </span>
                </span>
                <span className="text-[13px] text-muted">{formatUploaded(file.uploaded_at)}</span>
                <StatusBadge status={file.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
      {data && data.total > data.items.length && (
        <p className="text-sm text-muted">
          Showing {data.items.length} of {data.total}. Resolve these to see more.
        </p>
      )}
    </>
  );
}
