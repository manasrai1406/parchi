import { UserPlus } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";

import {
  useCreateUser,
  useResetPassword,
  useUpdateUser,
  useUsers,
  type UserAccount,
} from "@/api/queries";
import { can, ROLE_LABELS, useCurrentUser, type Role } from "@/auth/session";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { formatUploaded } from "@/lib/format";
import { cn } from "@/lib/utils";

const ROLES: Role[] = ["viewer", "reviewer", "admin"];
const ROLE_NOTES: Record<Role, string> = {
  viewer: "Looks at files and receipts, and uses the Query page.",
  reviewer: "Also uploads, fixes and resolves receipts, and approves AI reads.",
  admin: "Also deletes files and manages users.",
};
const GRID =
  "grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_150px_120px_150px_minmax(0,1.3fr)] gap-x-4 px-6";
const FIELD =
  "h-11 min-w-0 rounded-[10px] border border-input bg-sidebar px-3 text-sm text-text placeholder:text-muted";
const MIN_PASSWORD = 10;

/** A small modal with a form: Escape and Cancel close it, focus starts in the form. */
function FormDialog({
  title,
  submitLabel,
  busy,
  error,
  onSubmit,
  onClose,
  children,
}: {
  title: string;
  submitLabel: string;
  busy: boolean;
  error: string | null;
  onSubmit: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  const titleId = useId();
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    formRef.current?.querySelector<HTMLElement>("input, select")?.focus();
    return () => opener?.focus();
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onKeyDown={(event) => event.key === "Escape" && !busy && onClose()}
    >
      <form
        ref={formRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          onSubmit();
        }}
        className="flex w-full max-w-md flex-col gap-4 rounded-2xl border border-border bg-card p-6 shadow-[0_8px_24px_rgba(0,0,0,0.35)]"
      >
        <h2 id={titleId} className="font-heading text-xl font-semibold">
          {title}
        </h2>
        {children}
        {error && (
          <p role="alert" className="text-sm text-flagged">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="h-11 rounded-[10px] border border-input bg-raised px-4 text-sm font-medium disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="h-11 rounded-[10px] bg-accent px-5 text-sm font-semibold text-on-accent disabled:opacity-50"
          >
            {submitLabel}
          </button>
        </div>
      </form>
    </div>
  );
}

function LabelledInput({
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

function AddUserDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateUser();
  const roleId = useId();
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("reviewer");
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const submit = () => {
    if (!/^[A-Za-z0-9._-]{3,50}$/.test(username.trim())) {
      return setProblem("Usernames are 3 to 50 letters, digits, dots, dashes or underscores.");
    }
    if (password.length < MIN_PASSWORD) {
      return setProblem(`The temporary password needs at least ${MIN_PASSWORD} characters.`);
    }
    setProblem(null);
    create.mutate(
      {
        username: username.trim(),
        display_name: name.trim(),
        role,
        temporary_password: password,
      },
      { onSuccess: onClose },
    );
  };

  return (
    <FormDialog
      title="Add a user"
      submitLabel={create.isPending ? "Adding…" : "Add user"}
      busy={create.isPending}
      error={problem ?? (create.error instanceof Error ? create.error.message : null)}
      onSubmit={submit}
      onClose={onClose}
    >
      <LabelledInput
        label="Username (cannot be changed later)"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
        maxLength={50}
        autoComplete="off"
        required
      />
      <LabelledInput
        label="Name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        maxLength={100}
        required
      />
      <div className="flex flex-col gap-1.5">
        <label htmlFor={roleId} className="text-[13px] font-medium text-[#B5C4BD]">
          Role
        </label>
        <select
          id={roleId}
          value={role}
          onChange={(event) => setRole(event.target.value as Role)}
          className={FIELD}
        >
          {ROLES.map((option) => (
            <option key={option} value={option}>
              {ROLE_LABELS[option]}
            </option>
          ))}
        </select>
        <span className="text-xs text-muted">{ROLE_NOTES[role]}</span>
      </div>
      <LabelledInput
        label={`Temporary password (${MIN_PASSWORD} or more characters)`}
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        maxLength={128}
        required
      />
      <p className="text-xs text-muted">
        Give them the temporary password yourself. They choose their own at the first login.
      </p>
    </FormDialog>
  );
}

function ResetPasswordDialog({ user, onClose }: { user: UserAccount; onClose: () => void }) {
  const reset = useResetPassword();
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const submit = () => {
    if (password.length < MIN_PASSWORD) {
      return setProblem(`Use at least ${MIN_PASSWORD} characters.`);
    }
    setProblem(null);
    reset.mutate({ id: user.id, temporary_password: password }, { onSuccess: onClose });
  };
  return (
    <FormDialog
      title={`Reset ${user.display_name}'s password`}
      submitLabel={reset.isPending ? "Resetting…" : "Reset password"}
      busy={reset.isPending}
      error={problem ?? (reset.error instanceof Error ? reset.error.message : null)}
      onSubmit={submit}
      onClose={onClose}
    >
      <LabelledInput
        label="Temporary password"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        maxLength={128}
        required
      />
      <p className="text-xs text-muted">
        They are logged out everywhere and must choose a new password at the next login.
      </p>
    </FormDialog>
  );
}

function StatusChip({ user }: { user: UserAccount }) {
  if (!user.active) {
    return <span className="text-sm text-muted">Deactivated</span>;
  }
  return (
    <span
      className={cn("text-sm", user.must_change_password ? "text-review" : "text-success-text")}
    >
      {user.must_change_password ? "Password to set" : "Active"}
    </span>
  );
}

export function UsersPage() {
  const me = useCurrentUser();
  const { data: users, isPending, isError, error } = useUsers();
  const update = useUpdateUser();
  const [adding, setAdding] = useState(false);
  const [resetting, setResetting] = useState<UserAccount | null>(null);
  const [deactivating, setDeactivating] = useState<UserAccount | null>(null);

  if (!can(me, "admin")) {
    return (
      <>
        <PageHeader eyebrow="Accounts" title="Users" />
        <p className="text-muted">Only admins can manage users.</p>
      </>
    );
  }

  return (
    <>
      <div className="flex items-end justify-between gap-6">
        <PageHeader eyebrow="Accounts" title="Users" />
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="inline-flex h-11 items-center gap-2 rounded-[10px] bg-accent px-4.5 text-sm font-semibold text-on-accent"
        >
          <UserPlus size={18} strokeWidth={1.8} aria-hidden="true" />
          Add user
        </button>
      </div>
      {update.error instanceof Error && (
        <p role="alert" className="text-sm text-flagged">
          {update.error.message}
        </p>
      )}

      <section
        aria-label="Users"
        className="overflow-hidden rounded-2xl border border-border bg-card shadow-[0_8px_24px_rgba(0,0,0,0.35)]"
      >
        <div role="table" aria-label="Users">
          <div
            role="row"
            className={cn(
              GRID,
              "h-10 items-center border-b border-border bg-sidebar text-xs font-semibold tracking-[0.08em] text-muted uppercase",
            )}
          >
            <span role="columnheader">Name</span>
            <span role="columnheader">Username</span>
            <span role="columnheader">Role</span>
            <span role="columnheader">Status</span>
            <span role="columnheader">Last login</span>
            <span role="columnheader" className="text-right">
              Actions
            </span>
          </div>
          {users?.map((user) => {
            const isMe = user.id === me?.id;
            return (
              <div
                key={user.id}
                role="row"
                className={cn(
                  GRID,
                  "min-h-16 items-center border-t border-divider py-2 first:border-t-0",
                )}
              >
                <span role="cell" className="truncate font-medium">
                  {user.display_name}
                  {isMe && <span className="ml-2 text-xs text-muted">(you)</span>}
                </span>
                <span role="cell" className="truncate font-mono text-[13px]">
                  {user.username}
                </span>
                <span role="cell">
                  {isMe ? (
                    <span className="text-sm">{ROLE_LABELS[user.role]}</span>
                  ) : (
                    <select
                      aria-label={`Role for ${user.username}`}
                      value={user.role}
                      disabled={update.isPending}
                      onChange={(event) =>
                        update.mutate({ id: user.id, role: event.target.value as Role })
                      }
                      className={cn(FIELD, "h-10 w-full")}
                    >
                      {ROLES.map((option) => (
                        <option key={option} value={option}>
                          {ROLE_LABELS[option]}
                        </option>
                      ))}
                    </select>
                  )}
                </span>
                <span role="cell">
                  <StatusChip user={user} />
                </span>
                <span role="cell" className="text-sm text-muted">
                  {user.last_login_at ? formatUploaded(user.last_login_at) : "Never"}
                </span>
                <span role="cell" className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setResetting(user)}
                    className="h-10 rounded-[10px] border border-input px-3 text-sm"
                  >
                    Reset password…
                  </button>
                  {!isMe &&
                    (user.active ? (
                      <button
                        type="button"
                        onClick={() => setDeactivating(user)}
                        className="h-10 rounded-[10px] border border-input px-3 text-sm text-flagged"
                      >
                        Deactivate
                      </button>
                    ) : (
                      <button
                        type="button"
                        disabled={update.isPending}
                        onClick={() => update.mutate({ id: user.id, active: true })}
                        className="h-10 rounded-[10px] border border-input px-3 text-sm"
                      >
                        Reactivate
                      </button>
                    ))}
                </span>
              </div>
            );
          })}
        </div>
        {isPending && <p className="px-6 py-8 text-muted">Loading users…</p>}
        {isError && (
          <p role="alert" className="px-6 py-8 text-flagged">
            {error instanceof Error ? error.message : "Could not load users."}
          </p>
        )}
      </section>

      {adding && <AddUserDialog onClose={() => setAdding(false)} />}
      {resetting && <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />}
      {deactivating && (
        <ConfirmDialog
          title={`Deactivate ${deactivating.display_name}?`}
          confirmLabel="Deactivate"
          busyLabel="Deactivating…"
          busy={update.isPending}
          error={update.error instanceof Error ? update.error.message : null}
          onCancel={() => setDeactivating(null)}
          onConfirm={() =>
            update.mutate(
              { id: deactivating.id, active: false },
              { onSuccess: () => setDeactivating(null) },
            )
          }
        >
          <p>
            <span className="font-mono text-text">{deactivating.username}</span> is logged out and
            cannot log in until reactivated. What they did stays signed with their name.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}
