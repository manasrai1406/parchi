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

function setup(deleteAnswer: { status: number; body?: unknown } = { status: 204 }) {
  return mockApi((url, method) => {
    if (url === "/api/health/ready") return { body: READY };
    if (method === "DELETE") return deleteAnswer;
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

describe("deleting a file", () => {
  it("asks first, starting on Cancel, and can be cancelled", async () => {
    const fetchMock = setup();
    renderAt("/files");
    fireEvent.click(await screen.findByRole("button", { name: "Delete inv_0421.pdf" }));

    const dialog = screen.getByRole("alertdialog", { name: "Delete inv_0421.pdf?" });
    expect(dialog.textContent).toContain("REF-2026-000001");
    expect(document.activeElement?.textContent).toBe("Cancel");

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
  });

  it("deletes by reference number and refreshes the list", async () => {
    const fetchMock = setup();
    renderAt("/files");
    fireEvent.click(await screen.findByRole("button", { name: "Delete inv_0421.pdf" }));
    const listCallsBefore = filesCalls(fetchMock).length;

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(fetchMock).toHaveBeenCalledWith("/api/files/REF-2026-000001", { method: "DELETE" });
    await waitFor(() => expect(filesCalls(fetchMock).length).toBeGreaterThan(listCallsBefore));
  });

  it("shows why a delete was refused and keeps the dialog open", async () => {
    setup({
      status: 409,
      body: { code: "file_busy", message: "This file is being processed.", request_id: "r" },
    });
    renderAt("/files");
    fireEvent.click(await screen.findByRole("button", { name: "Delete inv_0421.pdf" }));

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("This file is being processed.")).toBeTruthy();
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });

  it("cannot be started while a file is being processed", async () => {
    FILES[0]!.status = "processing";
    try {
      setup();
      renderAt("/files");
      const button = await screen.findByRole("button", { name: "Delete inv_0421_copy.pdf" });
      expect((button as HTMLButtonElement).disabled).toBe(true);
    } finally {
      FILES[0]!.status = "pending";
    }
  });
});
