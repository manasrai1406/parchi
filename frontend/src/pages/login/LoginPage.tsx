import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { useLogin, useMe } from "@/auth/session";
import { Logo } from "@/components/Sidebar";

const FIELD =
  "h-11 rounded-[10px] border border-input bg-sidebar px-3.5 text-[15px] text-text placeholder:text-muted";

/** The centred card the login and password pages share. */
export function AuthCard({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <main className="flex min-h-full items-center justify-center p-6">
      <div className="flex w-full max-w-sm flex-col gap-6 rounded-2xl border border-border bg-card p-7 shadow-[0_8px_24px_rgba(0,0,0,0.35)]">
        <Logo />
        <div>
          <h1 className="font-heading text-2xl font-semibold">{title}</h1>
          {note && <p className="mt-1.5 text-sm text-muted">{note}</p>}
        </div>
        {children}
      </div>
    </main>
  );
}

export function Field({
  label,
  ...input
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[13px] font-medium text-[#B5C4BD]">
        {label}
      </label>
      <input id={id} className={FIELD} {...input} />
    </div>
  );
}

export function LoginPage() {
  const { data: me, isPending } = useMe();
  const login = useLogin();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/files";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  if (isPending) return null;
  if (me) return <Navigate to={from} replace />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate(
      { username: username.trim(), password },
      { onSuccess: () => navigate(from, { replace: true }) },
    );
  };

  return (
    <AuthCard title="Log in">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field
          label="Username"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          maxLength={50}
          required
          autoFocus
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          maxLength={128}
          required
        />
        {login.error instanceof Error && (
          <p role="alert" className="text-sm text-flagged">
            {login.error.message}
          </p>
        )}
        <button
          type="submit"
          disabled={login.isPending || !username.trim() || !password}
          className="h-11 rounded-[10px] bg-accent text-[15px] font-semibold text-on-accent disabled:opacity-50"
        >
          {login.isPending ? "Logging in…" : "Log in"}
        </button>
      </form>
      <p className="text-xs text-muted">Forgot your password? Ask an admin to reset it.</p>
    </AuthCard>
  );
}
