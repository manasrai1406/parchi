import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { createBatch, uploadFile } from "@/api/upload";
import { mockApi, READY, renderAt } from "@/test/render";

vi.mock("@/api/upload", () => ({ createBatch: vi.fn(), uploadFile: vi.fn() }));

const createBatchMock = vi.mocked(createBatch);
const uploadFileMock = vi.mocked(uploadFile);

function summary(id: number, name: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    ref_no: `REF-2026-00000${id}`,
    original_name: name,
    size_bytes: 184 * 1024,
    kind: null,
    status: "pending" as const,
    error: null,
    uploaded_at: "2026-09-26T10:00:00Z",
    duplicate_of: null,
    ...extra,
  };
}

function pdf(name: string) {
  return new File(["%PDF-1.4"], name, { type: "application/pdf" });
}

async function drop(...files: File[]) {
  const input = screen.getByLabelText("Choose files to upload");
  fireEvent.change(input, { target: { files } });
}

beforeEach(() => {
  mockApi((url) => {
    if (url === "/api/health/ready") return { body: READY };
    const batch = url.match(/^\/api\/batches\/(\d+)$/);
    if (batch) return { body: { id: Number(batch[1]), created_at: "", files: [] } };
  });
  createBatchMock.mockResolvedValue({ id: 1, created_at: "2026-09-26T10:00:00Z" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("Upload page", () => {
  it("uploads a dropped file and shows its reference number", async () => {
    uploadFileMock.mockResolvedValue({ result: "registered", file: summary(1, "inv_0421.pdf") });
    renderAt("/upload");

    await drop(pdf("inv_0421.pdf"));

    expect(await screen.findByText("REF-2026-000001")).toBeTruthy();
    expect(screen.getByText("Queued")).toBeTruthy();
    expect(uploadFileMock).toHaveBeenCalledWith(
      1,
      expect.any(File),
      expect.objectContaining({ confirmDuplicate: false }),
    );
  });

  it("asks before keeping a duplicate, and re-sends it confirmed", async () => {
    uploadFileMock
      .mockResolvedValueOnce({
        result: "duplicate",
        duplicate_of: { id: 1, ref_no: "REF-2026-000001", original_name: "inv_0421.pdf" },
      })
      .mockResolvedValueOnce({
        result: "registered",
        file: summary(2, "inv_0421_copy.pdf", {
          duplicate_of: { id: 1, ref_no: "REF-2026-000001", original_name: "inv_0421.pdf" },
        }),
      });
    renderAt("/upload");

    await drop(pdf("inv_0421_copy.pdf"));
    fireEvent.click(await screen.findByRole("button", { name: "Keep a copy" }));

    expect(await screen.findByText("REF-2026-000002")).toBeTruthy();
    expect(uploadFileMock).toHaveBeenLastCalledWith(
      1,
      expect.any(File),
      expect.objectContaining({ confirmDuplicate: true }),
    );
  });

  it("skips a duplicate without sending anything more", async () => {
    uploadFileMock.mockResolvedValue({
      result: "duplicate",
      duplicate_of: { id: 1, ref_no: "REF-2026-000001", original_name: "inv_0421.pdf" },
    });
    renderAt("/upload");

    await drop(pdf("inv_0421_copy.pdf"));
    fireEvent.click(await screen.findByRole("button", { name: "Skip" }));

    expect(await screen.findByText("Skipped")).toBeTruthy();
    expect(uploadFileMock).toHaveBeenCalledTimes(1);
  });

  it("refuses unsupported files without uploading them", async () => {
    renderAt("/upload");

    await drop(new File(["MZ"], "setup.exe", { type: "application/x-msdownload" }));

    expect(await screen.findByText("This file type is not accepted.")).toBeTruthy();
    expect(uploadFileMock).not.toHaveBeenCalled();
  });

  it("shows the server's message when an upload fails", async () => {
    uploadFileMock.mockRejectedValue(
      new ApiError(413, {
        code: "file_too_large",
        message: "Files can be at most 20 MB.",
        request_id: "r",
      }),
    );
    renderAt("/upload");

    await drop(pdf("huge.pdf"));

    expect(await screen.findByText("Files can be at most 20 MB.")).toBeTruthy();
  });

  it("starts a new batch when the current one is full", async () => {
    createBatchMock
      .mockResolvedValueOnce({ id: 1, created_at: "" })
      .mockResolvedValueOnce({ id: 2, created_at: "" });
    uploadFileMock
      .mockRejectedValueOnce(
        new ApiError(409, { code: "batch_full", message: "Full", request_id: null }),
      )
      .mockResolvedValueOnce({ result: "registered", file: summary(3, "a.pdf") });
    renderAt("/upload");

    await drop(pdf("a.pdf"));

    await waitFor(() => expect(uploadFileMock).toHaveBeenCalledTimes(2));
    expect(uploadFileMock.mock.calls[1]?.[0]).toBe(2);
    expect(await screen.findByText("REF-2026-000003")).toBeTruthy();
  });
});
