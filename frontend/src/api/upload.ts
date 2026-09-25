import { API_BASE, ApiError, type Schemas } from "./client";

export type UploadResult = Schemas["RegisteredResult"] | Schemas["DuplicateResult"];

export async function createBatch(): Promise<Schemas["BatchOut"]> {
  const response = await fetch(`${API_BASE}/batches`, { method: "POST" });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw toApiError(response.status, body);
  return body as Schemas["BatchOut"];
}

function toApiError(status: number, body: unknown): ApiError {
  const error = body as Partial<Schemas["ErrorResponse"]> | null;
  return new ApiError(status, {
    code: error?.code ?? "http_error",
    message: error?.message ?? `Upload failed (${status})`,
    request_id: error?.request_id ?? null,
  });
}

/**
 * Send one file (D-017). XMLHttpRequest instead of fetch, because only it reports
 * upload progress.
 */
export function uploadFile(
  batchId: number,
  file: File,
  {
    confirmDuplicate = false,
    onProgress,
  }: { confirmDuplicate?: boolean; onProgress?: (fraction: number) => void } = {},
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("confirm_duplicate", confirmDuplicate ? "true" : "false");

    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE}/batches/${batchId}/files`);
    request.responseType = "json";
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    request.onload = () => {
      if (request.status === 200 || request.status === 201) {
        resolve(request.response as UploadResult);
      } else {
        reject(toApiError(request.status, request.response));
      }
    };
    request.onerror = () =>
      reject(
        new ApiError(0, {
          code: "network_error",
          message: "Could not reach the server.",
          request_id: null,
        }),
      );
    request.send(form);
  });
}
