import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { FileRejection } from "react-dropzone";

import { ApiError, type Schemas } from "@/api/client";
import { createBatch, uploadFile } from "@/api/upload";

/** Files sent at the same time. */
const CONCURRENCY = 3;

export type UploadItem = {
  key: string;
  file: File;
  phase: "waiting" | "uploading" | "registered" | "duplicate" | "skipped" | "error";
  progress: number;
  confirmDuplicate: boolean;
  batchId?: number;
  registered?: Schemas["FileSummary"];
  duplicateOf?: Schemas["FileRef"];
  error?: string;
};

type Action =
  | { type: "add"; items: UploadItem[] }
  | { type: "update"; key: string; patch: Partial<UploadItem> };

function reducer(items: UploadItem[], action: Action): UploadItem[] {
  switch (action.type) {
    case "add":
      return [...items, ...action.items];
    case "update":
      return items.map((item) => (item.key === action.key ? { ...item, ...action.patch } : item));
  }
}

let nextKey = 0;
const newKey = () => `upload-${nextKey++}`;

const REJECTION_MESSAGES: Record<string, string> = {
  "file-too-large": "Larger than 20 MB.",
  "file-invalid-type": "This file type is not accepted.",
};

export function useUploadSession() {
  const [items, dispatch] = useReducer(reducer, []);
  const active = useRef(0);
  // Keys already handed to `send`, so the queue never starts one twice.
  const taken = useRef(new Set<string>());
  const batch = useRef<Promise<number> | null>(null);

  const update = useCallback(
    (key: string, patch: Partial<UploadItem>) => dispatch({ type: "update", key, patch }),
    [],
  );

  const currentBatch = useCallback((): Promise<number> => {
    batch.current ??= createBatch().then((created) => created.id);
    batch.current.catch(() => {
      batch.current = null;
    });
    return batch.current;
  }, []);

  const send = useCallback(
    async (item: UploadItem): Promise<void> => {
      // A full batch (409 batch_full) is retried once in a fresh batch.
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const batchId = await currentBatch();
          update(item.key, { phase: "uploading", progress: 0, batchId, error: undefined });
          const result = await uploadFile(batchId, item.file, {
            confirmDuplicate: item.confirmDuplicate,
            onProgress: (progress) => update(item.key, { progress }),
          });
          if (result.result === "registered") {
            update(item.key, { phase: "registered", progress: 1, registered: result.file });
          } else {
            update(item.key, { phase: "duplicate", duplicateOf: result.duplicate_of });
          }
          return;
        } catch (error) {
          if (error instanceof ApiError && error.code === "batch_full" && attempt === 0) {
            batch.current = null;
            continue;
          }
          const message = error instanceof Error ? error.message : "Upload failed.";
          update(item.key, { phase: "error", error: message });
          return;
        }
      }
    },
    [currentBatch, update],
  );

  // Bumped when an upload finishes, so the queue below looks for the next file.
  const [finished, setFinished] = useState(0);

  useEffect(() => {
    while (active.current < CONCURRENCY) {
      const next = items.find((item) => item.phase === "waiting" && !taken.current.has(item.key));
      if (!next) return;
      taken.current.add(next.key);
      active.current += 1;
      void send(next).finally(() => {
        active.current -= 1;
        taken.current.delete(next.key);
        setFinished((count) => count + 1);
      });
    }
  }, [items, finished, send]);

  const addFiles = useCallback((accepted: File[], rejected: FileRejection[] = []) => {
    const base = { progress: 0, confirmDuplicate: false };
    dispatch({
      type: "add",
      items: [
        ...accepted.map((file) => ({ ...base, key: newKey(), file, phase: "waiting" as const })),
        ...rejected.map(({ file, errors }) => ({
          ...base,
          key: newKey(),
          file,
          phase: "error" as const,
          error: REJECTION_MESSAGES[errors[0]?.code ?? ""] ?? errors[0]?.message ?? "Not accepted.",
        })),
      ],
    });
  }, []);

  /** "Keep a copy": upload the same file again, confirming the duplicate (D-015). */
  const keepDuplicate = useCallback(
    (key: string) => update(key, { phase: "waiting", confirmDuplicate: true, progress: 0 }),
    [update],
  );

  const skipDuplicate = useCallback((key: string) => update(key, { phase: "skipped" }), [update]);

  const batchIds = [
    ...new Set(items.flatMap((item) => (item.registered && item.batchId ? [item.batchId] : []))),
  ];

  return { items, batchIds, addFiles, keepDuplicate, skipDuplicate };
}
