import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, READY, renderAt } from "@/test/render";

const FILES = [
  {
    id: 2,
    ref_no: "REF-2026-000002",
    original_name: "inv_0421_copy.pdf",
    size_bytes: 1000,
    kind: null,
    status: "pending",
    error: null,
    uploaded_at: "2026-09-26T10:00:00Z",
    duplicate_of: { id: 1, ref_no: "REF-2026-000001", original_name: "inv_0421.pdf" },
  },
  {
    id: 1,
    ref_no: "REF-2026-000001",
    original_name: "inv_0421.pdf",
    size_bytes: 1000,
    kind: null,
    status: "pending",
    error: null,
    uploaded_at: "2026-09-26T09:00:00Z",
    duplicate_of: null,
  },
];

function setup() {
  return mockApi((url) => {
    if (url === "/api/health/ready") return { body: READY };
    if (url.startsWith("/api/files?")) {
      return { body: { items: FILES, total: FILES.length, page: 1, page_size: 25 } };
    }
  });
}

function filesCalls(fetchMock: ReturnType<typeof setup>): URLSearchParams[] {
  return fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.startsWith("/api/files?"))
    .map((url) => new URLSearchParams(url.split("?")[1]));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Files page", () => {
  it("lists files with reference numbers, copies and downloads", async () => {
    setup();
    renderAt("/files");

    expect(await screen.findByText("inv_0421_copy.pdf")).toBeTruthy();
    expect(screen.getAllByText("REF-2026-000001").length).toBe(2); // its row, and the copy's link
    expect(screen.getByText("Showing 2 of 2 files")).toBeTruthy();

    const download = screen.getByRole("link", { name: "Download inv_0421.pdf" });
    expect(download.getAttribute("href")).toBe("/api/files/REF-2026-000001/download");
  });

  it("filters by status with the chips", async () => {
    const fetchMock = setup();
    renderAt("/files");
    await screen.findByText("inv_0421.pdf");

    fireEvent.click(screen.getByRole("button", { name: "Needs review" }));

    await waitFor(() => expect(filesCalls(fetchMock).at(-1)?.get("status")).toBe("needs_review"));
    expect(screen.getByRole("button", { name: "Needs review" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
  });

  it("searches by name or reference", async () => {
    const fetchMock = setup();
    renderAt("/files");
    await screen.findByText("inv_0421.pdf");

    fireEvent.change(screen.getByLabelText("Search name or reference"), {
      target: { value: "REF-2026-000002" },
    });

    await waitFor(() => expect(filesCalls(fetchMock).at(-1)?.get("q")).toBe("REF-2026-000002"));
  });
});
