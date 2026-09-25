import type { components } from "./schema";

export type Schemas = components["schemas"];
export type ErrorBody = Schemas["ErrorResponse"];

/** The API is reached through /api (proxied to FastAPI in development). */
export const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.requestId = body.request_id;
  }
}

function isErrorBody(value: unknown): value is ErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ErrorBody).code === "string" &&
    typeof (value as ErrorBody).message === "string"
  );
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      isErrorBody(body)
        ? body
        : { code: "http_error", message: `Request failed (${response.status})`, request_id: null },
    );
  }
  return body as T;
}

/** DELETE, expecting 204 No Content. */
export async function apiDelete(path: string): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      isErrorBody(body)
        ? body
        : { code: "http_error", message: `Request failed (${response.status})`, request_id: null },
    );
  }
}
