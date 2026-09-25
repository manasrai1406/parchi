import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, READY, renderAt } from "@/test/render";

const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 25 };

function api(ready: { status: number; body: unknown } = { status: 200, body: READY }) {
  return mockApi((url) => {
    if (url === "/api/health/ready") return ready;
    if (url.startsWith("/api/files?")) return { body: EMPTY_PAGE };
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("app shell", () => {
  it("shows the four pages in the sidebar and marks the current one", async () => {
    api();
    renderAt("/files");

    const nav = screen.getByRole("navigation", { name: "Main" });
    const links = Array.from(nav.querySelectorAll("a")).map((a) => a.textContent);
    expect(links).toEqual(["Upload", "Files", "Review", "Query"]);
    expect(screen.getByRole("link", { name: "Files" }).getAttribute("aria-current")).toBe("page");
    expect(await screen.findByRole("heading", { name: "Files" })).toBeTruthy();
  });

  it("sends / to the Files page", async () => {
    api();
    const router = renderAt("/");
    await screen.findByRole("heading", { name: "Files" });
    expect(router.state.location.pathname).toBe("/files");
  });

  it("reports the system as connected when the API is ready", async () => {
    const fetchMock = api();
    renderAt("/upload");
    expect(await screen.findByText("Connected")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/health/ready", expect.anything());
  });

  it("shows the message from the API when a service is down", async () => {
    api({
      status: 503,
      body: { code: "not_ready", message: "Unavailable: redis", request_id: "abc" },
    });
    renderAt("/upload");
    expect(await screen.findByText("Unavailable")).toBeTruthy();
    expect(screen.getByText("Unavailable: redis")).toBeTruthy();
  });
});
