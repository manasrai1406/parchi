import { FileCheck2, List, Search, Upload, type LucideIcon } from "lucide-react";
import { NavLink } from "react-router";

import { useAiUsage, useReadiness, useSummary } from "@/api/queries";
import { cn } from "@/lib/utils";

// The badge counts files needing attention: needs review, flagged, or with open warnings.
const NAV_ITEMS: { to: string; label: string; icon: LucideIcon; badge?: boolean }[] = [
  { to: "/upload", label: "Upload", icon: Upload },
  { to: "/files", label: "Files", icon: List, badge: true },
  { to: "/review", label: "Review", icon: FileCheck2, badge: true },
  { to: "/query", label: "Query", icon: Search },
];

function Logo() {
  return (
    <div className="flex items-center gap-3 px-2">
      <div className="flex size-[34px] items-center justify-center rounded-[10px] bg-accent text-on-accent">
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M6 3h12v18l-3-2-3 2-3-2-3 2z" />
          <path d="M9 8h6" />
          <path d="M9 12h6" />
        </svg>
      </div>
      <span className="font-heading text-[19px] font-semibold tracking-[-0.01em]">Parchi</span>
    </div>
  );
}

const STATUS_LABELS = { checking: "Checking…", down: "Unavailable", up: "Connected" } as const;

/** Readiness of the API, PostgreSQL and Redis, from GET /health/ready. */
function SystemStatus() {
  const { isPending, isError, error } = useReadiness();
  const state = isPending ? "checking" : isError ? "down" : "up";

  return (
    <div
      className="flex flex-col gap-2.5 rounded-xl border border-border bg-card p-3.5"
      aria-live="polite"
    >
      <span className="text-xs text-muted">System</span>
      <span className="flex items-center gap-2 text-[15px] font-semibold">
        <span
          aria-hidden="true"
          className={cn(
            "size-2 rounded-full",
            state === "up" && "bg-success",
            state === "down" && "bg-flagged",
            state === "checking" && "bg-pending",
          )}
        />
        {STATUS_LABELS[state]}
      </span>
      <span className="text-xs text-muted">
        {state === "down" && error instanceof Error ? error.message : "API, database and Redis."}
      </span>
    </div>
  );
}

/** From the design: approved AI reads today against the daily cap (GET /ai/usage). */
function AiUsageCard() {
  const { data: usage } = useAiUsage();
  if (!usage) return null;
  const share = usage.daily_cap ? Math.min(usage.used_today / usage.daily_cap, 1) : 0;
  return (
    <div className="flex flex-col gap-2.5 rounded-xl border border-border bg-card p-3.5">
      <span className="text-xs text-muted">AI approved today</span>
      <span className="text-[15px] font-semibold">
        {usage.enabled ? `${usage.used_today} of ${usage.daily_cap}` : "AI is off"}
      </span>
      {usage.enabled && (
        <div
          className="h-1.5 rounded-full bg-track"
          role="progressbar"
          aria-label="AI approvals used today"
          aria-valuenow={usage.used_today}
          aria-valuemin={0}
          aria-valuemax={usage.daily_cap}
        >
          <div className="h-1.5 rounded-full bg-accent" style={{ width: `${share * 100}%` }} />
        </div>
      )}
      <span className="text-xs text-muted">AI runs only when you approve it.</span>
    </div>
  );
}

export function Sidebar() {
  const attention = useSummary().data?.needs_attention ?? 0;
  return (
    <aside className="flex w-60 shrink-0 flex-col gap-7 border-r border-border bg-sidebar px-4 py-6">
      <Logo />
      <nav aria-label="Main" className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ to, label, icon: Icon, badge }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex h-11 items-center gap-3 rounded-[10px] px-3 text-[15px]",
                isActive
                  ? "bg-accent-soft font-semibold text-accent-text"
                  : "font-medium text-nav hover:bg-card",
              )
            }
          >
            <Icon size={20} strokeWidth={1.8} aria-hidden="true" />
            <span>{label}</span>
            {badge && attention > 0 && (
              <span
                className="ml-auto rounded-full bg-review-bg px-2 py-0.5 text-xs font-semibold text-review"
                aria-label={`${attention} need attention`}
              >
                {attention}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto flex flex-col gap-3">
        <AiUsageCard />
        <SystemStatus />
      </div>
    </aside>
  );
}
