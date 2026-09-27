import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";

import { useChangePassword, useLogout, useMe } from "@/auth/session";

import { AuthCard, Field } from "./LoginPage";

const MIN = 10;
const MAX = 128;

export function ChangePasswordPage() {
  const { data: me, isPending } = useMe();
  const change = useChangePassword();
  const logout = useLogout();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  if (isPending) return null;
  if (!me) return <Navigate to="/login" replace />;
  const forced = me.must_change_password;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (next.length < MIN) return setProblem(`Use at least ${MIN} characters.`);
    if (next !== again) return setProblem("The two new passwords do not match.");
    setProblem(null);
    change.mutate(
      { current_password: current, new_password: next },
      { onSuccess: () => navigate("/files", { replace: true }) },
    );
  };

  return (
    <AuthCard
      title={forced ? "Choose your own password" : "Change password"}
      note={
        forced
          ? `Welcome, ${me.display_name}. Your password was set by an admin; choose a new one to continue.`
          : "Other devices where you are logged in will be logged out."
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field
          label={forced ? "Temporary password" : "Current password"}
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          maxLength={MAX}
          required
          autoFocus
        />
        <Field
          label={`New password (${MIN} or more characters)`}
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(event) => setNext(event.target.value)}
          maxLength={MAX}
          required
        />
        <Field
          label="New password again"
          type="password"
          autoComplete="new-password"
          value={again}
          onChange={(event) => setAgain(event.target.value)}
          maxLength={MAX}
          required
        />
        {(problem || change.error instanceof Error) && (
          <p role="alert" className="text-sm text-flagged">
            {problem ?? (change.error as Error).message}
          </p>
        )}
        <button
          type="submit"
          disabled={change.isPending}
          className="h-11 rounded-[10px] bg-accent text-[15px] font-semibold text-on-accent disabled:opacity-50"
        >
          {change.isPending ? "Saving…" : "Save new password"}
        </button>
      </form>
      <div className="flex justify-between text-sm">
        {forced ? (
          <button
            type="button"
            onClick={() => logout.mutate()}
            className="min-h-11 text-accent-text underline underline-offset-2"
          >
            Log out
          </button>
        ) : (
          <Link to="/files" className="inline-flex min-h-11 items-center text-accent-text">
            Back to Parchi
          </Link>
        )}
      </div>
    </AuthCard>
  );
}
