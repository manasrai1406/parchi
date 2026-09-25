import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routes } from "./routes";

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

const READY = { status: "ok", database: "ok", redis: "ok" };

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("app shell", () => {
  it("shows the four pages in the sidebar and marks the current one", async () => {
    mockFetch(200, READY);
    renderAt("/files");

    const nav = screen.getByRole("navigation", { name: "Main" });
    const links = Array.from(nav.querySelectorAll("a")).map((a) => a.textContent);
    expect(links).toEqual(["Upload", "Files", "Review", "Query"]);
    expect(screen.getByRole("link", { name: "Files" }).getAttribute("aria-current")).toBe("page");
    expect(await screen.findByRole("heading", { name: "Files" })).toBeTruthy();
  });

  it("sends / to the Files page", async () => {
    mockFetch(200, READY);
    const router = renderAt("/");
    await screen.findByRole("heading", { name: "Files" });
    expect(router.state.location.pathname).toBe("/files");
  });

  it("reports the system as connected when the API is ready", async () => {
    mockFetch(200, READY);
    renderAt("/upload");
    expect(await screen.findByText("Connected")).toBeTruthy();
    expect(fetch).toHaveBeenCalledWith("/api/health/ready", expect.anything());
  });

  it("shows the message from the API when a service is down", async () => {
    mockFetch(503, { code: "not_ready", message: "Unavailable: redis", request_id: "abc" });
    renderAt("/upload");
    expect(await screen.findByText("Unavailable")).toBeTruthy();
    expect(screen.getByText("Unavailable: redis")).toBeTruthy();
  });
});
