import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";

import { createQueryClient } from "@/api/queryClient";
import { routes } from "@/routes";

/** Render the whole app at `path`, with a fresh query cache. */
export function renderAt(path: string) {
  const queryClient = createQueryClient({ queries: { retry: false } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

type Route = (url: string, method: string) => { status?: number; body?: unknown } | undefined;

export const ADMIN = {
  id: 1,
  username: "admin",
  display_name: "Asha Admin",
  role: "admin",
  must_change_password: false,
};

/**
 * Answer fetch calls by URL. Unmatched URLs get a 404 in the API's error shape.
 * GET /auth/me answers with `me` (an admin unless given; null means logged out).
 */
export function mockApi(route: Route, me: object | null = ADMIN) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const answer = route(url, method) ??
      (url === "/api/auth/me"
        ? me
          ? { body: me }
          : {
              status: 401,
              body: { code: "not_logged_in", message: "Please log in.", request_id: null },
            }
        : undefined) ?? {
        status: 404,
        body: { code: "not_found", message: "Not found", request_id: null },
      };
    const status = answer.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(answer.body), { status });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export const READY = { status: "ok", database: "ok", redis: "ok" };
