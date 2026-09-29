import { Lock, Pencil, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  useCategories,
  useCreateCategory,
  useDeleteCategory,
  useRenameCategory,
  type Category,
} from "@/api/queries";
import { can, useCurrentUser } from "@/auth/session";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { cn } from "@/lib/utils";

const FIELD =
  "h-11 min-w-0 rounded-[10px] border border-input bg-sidebar px-3 text-sm text-text placeholder:text-muted";
const BUTTON =
  "inline-flex h-10 items-center gap-1.5 rounded-[10px] border border-input bg-raised px-3 text-sm font-medium disabled:opacity-40";
const GRID = "grid grid-cols-[minmax(0,1fr)_140px_120px_minmax(0,220px)] gap-x-4 px-6";

function usedBy(count: number): string {
  if (count === 0) return "Not used";
  return count === 1 ? "1 receipt or vendor" : `${count} receipts or vendors`;
}

function AddCategory() {
  const create = useCreateCategory();
  const [name, setName] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) create.mutate(name, { onSuccess: () => setName("") });
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-1.5">
      <div className="flex gap-2">
        <input
          aria-label="New category name"
          placeholder="New category, e.g. Medical"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={50}
          className={cn(FIELD, "w-80")}
        />
        <button
          type="submit"
          disabled={!name.trim() || create.isPending}
          className="inline-flex h-11 items-center gap-2 rounded-[10px] bg-accent px-4.5 text-sm font-semibold text-on-accent disabled:opacity-50"
        >
          <Plus size={18} aria-hidden="true" />
          Add category
        </button>
      </div>
      {create.error instanceof Error && (
        <p role="alert" className="text-sm text-flagged">
          {create.error.message}
        </p>
      )}
    </form>
  );
}

function CategoryRow({
  category,
  editable,
  onDelete,
}: {
  category: Category;
  editable: boolean;
  onDelete: (category: Category) => void;
}) {
  const rename = useRenameCategory();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(category.name);

  const save = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim() === category.name) return setEditing(false);
    rename.mutate({ id: category.id, name }, { onSuccess: () => setEditing(false) });
  };

  return (
    <div
      role="row"
      className={cn(GRID, "min-h-15 items-center border-t border-divider py-2 first:border-t-0")}
    >
      <span role="cell" className="min-w-0">
        {editing ? (
          <form onSubmit={save} className="flex flex-col gap-1">
            <div className="flex gap-2">
              <input
                aria-label={`New name for ${category.name}`}
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={50}
                autoFocus
                className={cn(FIELD, "h-10 flex-1")}
              />
              <button type="submit" disabled={!name.trim() || rename.isPending} className={BUTTON}>
                Save
              </button>
              <button
                type="button"
                onClick={() => {
                  setName(category.name);
                  rename.reset();
                  setEditing(false);
                }}
                className={BUTTON}
              >
                Cancel
              </button>
            </div>
            {rename.error instanceof Error && (
              <span role="alert" className="text-xs text-flagged">
                {rename.error.message}
              </span>
            )}
          </form>
        ) : (
          <span className="font-medium">{category.name}</span>
        )}
      </span>
      <span role="cell" className="text-sm text-muted">
        {category.builtin ? (
          <span className="inline-flex items-center gap-1.5">
            <Lock size={14} aria-hidden="true" />
            Built-in
          </span>
        ) : (
          "Custom"
        )}
      </span>
      <span role="cell" className="text-sm text-muted">
        {usedBy(category.in_use)}
      </span>
      <span role="cell" className="flex justify-end gap-2">
        {editable && !category.builtin && !editing && (
          <>
            <button
              type="button"
              onClick={() => setEditing(true)}
              aria-label={`Rename ${category.name}`}
              className={BUTTON}
            >
              <Pencil size={15} aria-hidden="true" />
              Rename
            </button>
            <button
              type="button"
              onClick={() => onDelete(category)}
              disabled={category.in_use > 0}
              title={
                category.in_use > 0
                  ? "In use: move its receipts to another category first"
                  : undefined
              }
              aria-label={`Delete ${category.name}`}
              className={cn(BUTTON, "text-flagged")}
            >
              <Trash2 size={15} aria-hidden="true" />
              Delete
            </button>
          </>
        )}
      </span>
    </div>
  );
}

/** Built-in and custom categories in one place (D-026, D-049). */
export function CategoriesPage() {
  const editable = can(useCurrentUser(), "reviewer");
  const { data: categories, isPending, isError, error } = useCategories();
  const remove = useDeleteCategory();
  const [deleting, setDeleting] = useState<Category | null>(null);

  return (
    <>
      <div>
        <PageHeader eyebrow="Lists" title="Categories" />
        <p className="mt-2 text-muted">
          Eight built-in categories, plus any you add. Pick one for a receipt on the Review page.
        </p>
      </div>
      {editable && <AddCategory />}

      <section
        aria-label="Categories"
        className="overflow-hidden rounded-2xl border border-border bg-card shadow-[0_8px_24px_rgba(0,0,0,0.35)]"
      >
        <div role="table" aria-label="Categories">
          <div
            role="row"
            className={cn(
              GRID,
              "h-10 items-center border-b border-border bg-sidebar text-xs font-semibold tracking-[0.08em] text-muted uppercase",
            )}
          >
            <span role="columnheader">Name</span>
            <span role="columnheader">Kind</span>
            <span role="columnheader">Used by</span>
            <span role="columnheader" className="text-right">
              Actions
            </span>
          </div>
          {categories?.map((category) => (
            <CategoryRow
              key={category.id}
              category={category}
              editable={editable}
              onDelete={(target) => {
                remove.reset();
                setDeleting(target);
              }}
            />
          ))}
        </div>
        {isPending && <p className="px-6 py-8 text-muted">Loading categories…</p>}
        {isError && (
          <p role="alert" className="px-6 py-8 text-flagged">
            {error instanceof Error ? error.message : "Could not load categories."}
          </p>
        )}
      </section>

      {deleting && (
        <ConfirmDialog
          title={`Delete ${deleting.name}?`}
          confirmLabel="Delete"
          busyLabel="Deleting…"
          busy={remove.isPending}
          error={remove.error instanceof Error ? remove.error.message : null}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
        >
          <p>No receipt or vendor uses it, so nothing else changes.</p>
        </ConfirmDialog>
      )}
    </>
  );
}
