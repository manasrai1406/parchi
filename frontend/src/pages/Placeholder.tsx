import { PageHeader } from "@/components/PageHeader";

/** Stands in for a page until its phase is built. */
export function Placeholder({
  eyebrow,
  title,
  phase,
}: {
  eyebrow: string;
  title: string;
  phase: number;
}) {
  return (
    <>
      <PageHeader eyebrow={eyebrow} title={title} />
      <div className="rounded-2xl border border-border bg-card p-6 text-muted">
        This page arrives in phase {phase}.
      </div>
    </>
  );
}
