import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";

import { routes } from "@/routes";

/** Render the whole app at `path`, with a fresh query cache. */
export function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

type Route = (url: string) => { status?: number; body: unknown } | undefined;

/** Answer fetch calls by URL. Unmatched URLs get a 404 in the API's error shape. */
export function mockApi(route: Route) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const answer = route(url) ?? {
      status: 404,
      body: { code: "not_found", message: "Not found", request_id: null },
    };
    return new Response(JSON.stringify(answer.body), { status: answer.status ?? 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export const READY = { status: "ok", database: "ok", redis: "ok" };
