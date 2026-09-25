export function PageHeader({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div>
      <div className="text-xs font-semibold tracking-[0.12em] text-accent-text uppercase">
        {eyebrow}
      </div>
      <h1 className="mt-1.5 font-heading text-4xl font-semibold tracking-[-0.02em]">{title}</h1>
    </div>
  );
}
