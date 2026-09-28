import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";

import { useAuthOptions, useMe, useSignup } from "@/auth/session";

import { AuthCard, Field } from "./LoginPage";

const MIN = 10;
const MAX = 128;
const USERNAME = /^[A-Za-z0-9._-]{3,50}$/;

/** Create one's own account. It starts as a Viewer; an admin can promote it (D-046). */
export function SignupPage() {
  const { data: me, isPending } = useMe();
  const { data: options } = useAuthOptions();
  const signup = useSignup();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  if (isPending) return null;
  if (me) return <Navigate to="/files" replace />;

  if (options && !options.signup) {
    return (
      <AuthCard title="Create an account" note="Sign-up is turned off here.">
        <p className="text-sm text-muted">Ask an admin to create an account for you.</p>
        <Link to="/login" className="inline-flex min-h-11 items-center text-sm text-accent-text">
          Back to log in
        </Link>
      </AuthCard>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!USERNAME.test(username.trim())) {
      return setProblem("Usernames are 3 to 50 letters, digits, dots, dashes or underscores.");
    }
    if (password.length < MIN) return setProblem(`Use at least ${MIN} characters.`);
    if (password !== again) return setProblem("The two passwords do not match.");
    setProblem(null);
    signup.mutate(
      { username: username.trim(), display_name: name.trim(), password },
      { onSuccess: () => navigate("/files", { replace: true }) },
    );
  };

  return (
    <AuthCard
      title="Create an account"
      note="You can look at receipts and use the Query page. An admin can give you more access."
    >
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
          label="Your name"
          autoComplete="name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={100}
          required
        />
        <Field
          label={`Password (${MIN} or more characters)`}
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          maxLength={MAX}
          required
        />
        <Field
          label="Password again"
          type="password"
          autoComplete="new-password"
          value={again}
          onChange={(event) => setAgain(event.target.value)}
          maxLength={MAX}
          required
        />
        {(problem || signup.error instanceof Error) && (
          <p role="alert" className="text-sm text-flagged">
            {problem ?? (signup.error as Error).message}
          </p>
        )}
        <button
          type="submit"
          disabled={signup.isPending}
          className="h-11 rounded-[10px] bg-accent text-[15px] font-semibold text-on-accent disabled:opacity-50"
        >
          {signup.isPending ? "Creating…" : "Create account"}
        </button>
      </form>
      <p className="text-sm text-muted">
        Already have an account?{" "}
        <Link to="/login" className="text-accent-text">
          Log in
        </Link>
      </p>
    </AuthCard>
  );
}
