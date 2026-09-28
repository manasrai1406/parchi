import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FileDetail } from "@/api/queries";
import { mockApi, READY, renderAt } from "@/test/render";

const NOW = "2026-09-26T10:00:00Z";

function file(extra: Partial<FileDetail> = {}): FileDetail {
  return {
    id: 5,
    ref_no: "REF-2026-000005",
    original_name: "incomplete_bill.xlsx",
    size_bytes: 1000,
    kind: "excel",
    status: "needs_review",
    error: "The receipt is missing its date and total.",
    uploaded_at: NOW,
    duplicate_of: null,
    open_flags: 0,
    receipts: [],
    flags: [],
    runs: [
      {
        id: 9,
        parser: "excel",
        provider: null,
        model: null,
        confidence: 0.5,
        duration_ms: 10,
        accepted: false,
        error: null,
        ai_approved_by: null,
        ai_approved_at: null,
        finished_at: NOW,
        created_at: NOW,
        result: [
          {
            vendor: "Raju Hardware",
            receipt_number: "5512",
            receipt_date: null,
            subtotal: null,
            tax: null,
            total: null,
            line_items: [
              { description: "Paint brush", quantity: null, unit_price: null, amount: "120.00" },
            ],
            confidence: 0.5,
            source: "sheet: Sheet",
          },
        ],
      },
    ],
    ...extra,
  };
}

const CATEGORIES = [
  { id: 1, name: "Fuel", builtin: true, in_use: 0 },
  { id: 2, name: "Office", builtin: true, in_use: 0 },
];

function setup(detail: FileDetail = file()) {
  return mockApi((url, method) => {
    if (url === "/api/health/ready") return { body: READY };
    if (url === "/api/categories") return { body: CATEGORIES };
    if (url === `/api/files/${detail.ref_no}` && method === "GET") return { body: detail };
    if (url === `/api/files/${detail.ref_no}/receipts` && method === "PUT") {
      return { body: { ...detail, status: "resolved", error: null } };
    }
    if (url === `/api/files/${detail.ref_no}/reject`) {
      return { body: { ...detail, status: "rejected" } };
    }
    if (url.startsWith("/api/flags/")) return { body: { ...detail.flags[0], resolved: true } };
  });
}

function sentBody(fetchMock: ReturnType<typeof setup>, method: string): unknown {
  const call = fetchMock.mock.calls.find(([, init]) => init?.method === method);
  return call ? JSON.parse(String(call[1]?.body ?? "null")) : undefined;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Review page", () => {
  it("starts from what the library found and shows it next to the final value", async () => {
    setup();
    renderAt("/review/REF-2026-000005");

    expect(await screen.findByRole("heading", { name: "incomplete_bill.xlsx" })).toBeTruthy();
    expect(screen.getByText("The receipt is missing its date and total.")).toBeTruthy();
    expect((screen.getByLabelText("Vendor") as HTMLInputElement).value).toBe("Raju Hardware");
    expect((screen.getByLabelText("Receipt no.") as HTMLInputElement).value).toBe("5512");
    expect(screen.getAllByText("Raju Hardware").length).toBeGreaterThan(0); // library column
    expect((screen.getByLabelText("Item 1 amount") as HTMLInputElement).value).toBe("120.00");
    expect(screen.getByText(/can't be shown here/)).toBeTruthy(); // spreadsheets download
  });

  it("will not save without a date and total, and says why", async () => {
    const fetchMock = setup();
    renderAt("/review/REF-2026-000005");
    await screen.findByLabelText("Vendor");

    fireEvent.click(screen.getByRole("button", { name: "Accept and resolve" }));

    expect(await screen.findByText("The date is required.")).toBeTruthy();
    expect(screen.getByText(/The total is required/)).toBeTruthy();
    expect(sentBody(fetchMock, "PUT")).toBeUndefined();
  });

  it("saves the corrected receipt and reports it resolved", async () => {
    const fetchMock = setup();
    renderAt("/review/REF-2026-000005");
    await screen.findByLabelText("Vendor");

    fireEvent.change(screen.getByLabelText("Date"), { target: { value: "2026-08-20" } });
    fireEvent.change(screen.getByLabelText("Total"), { target: { value: "1,210.00" } });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Add item" }));
    fireEvent.change(screen.getByLabelText("Item 2 description"), { target: { value: "Nails" } });
    fireEvent.change(screen.getByLabelText("Item 2 amount"), { target: { value: "90" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept and resolve" }));

    expect(await screen.findByText("Saved. The file is resolved.")).toBeTruthy();
    expect(sentBody(fetchMock, "PUT")).toEqual({
      receipts: [
        {
          vendor: "Raju Hardware",
          receipt_number: "5512",
          receipt_date: "2026-08-20",
          subtotal: null,
          tax: null,
          total: "1210.00",
          category_id: 2,
          line_items: [
            { description: "Paint brush", quantity: null, unit_price: null, amount: "120.00" },
            { description: "Nails", quantity: null, unit_price: null, amount: "90" },
          ],
        },
      ],
      keep_as_test: true, // ticked by itself once something was corrected
    });
  });

  it("says what the reader learned, and keeps the receipt only if ticked", async () => {
    const detail = file();
    const fetchMock = mockApi((url, method) => {
      if (url === "/api/health/ready") return { body: READY };
      if (url === "/api/categories") return { body: CATEGORIES };
      if (url === `/api/files/${detail.ref_no}` && method === "GET") return { body: detail };
      if (method === "PUT") {
        return {
          body: {
            ...detail,
            status: "resolved",
            error: null,
            learned: [{ vendor: "Raju Hardware", field: "total", label: "kul rashi" }],
            kept_as_test: false,
          },
        };
      }
    });
    renderAt("/review/REF-2026-000005");
    await screen.findByLabelText("Vendor");
    const keep = screen.getByLabelText("Keep as a test receipt") as HTMLInputElement;
    expect(keep.checked).toBe(false); // nothing corrected yet

    fireEvent.change(screen.getByLabelText("Date"), { target: { value: "2026-08-20" } });
    fireEvent.change(screen.getByLabelText("Total"), { target: { value: "210" } });
    expect(keep.checked).toBe(true);
    fireEvent.click(keep);
    fireEvent.click(screen.getByRole("button", { name: "Accept and resolve" }));

    expect(
      await screen.findByText(
        "Parchi learned that “kul rashi” is the total on Raju Hardware's receipts.",
      ),
    ).toBeTruthy();
    expect((sentBody(fetchMock, "PUT") as { keep_as_test: boolean }).keep_as_test).toBe(false);
  });

  it("marks a warning as OK", async () => {
    const detail = file({
      status: "parsed",
      error: null,
      open_flags: 1,
      flags: [
        {
          id: 3,
          type: "arithmetic_mismatch",
          severity: "warning",
          detail: "Line items add up to ₹100.00, which does not match the total ₹500.00.",
          receipt_id: null,
          resolved: false,
          resolved_by: null,
          resolved_at: null,
          created_at: NOW,
        },
      ],
    });
    const fetchMock = setup(detail);
    renderAt("/review/REF-2026-000005");

    expect(await screen.findByText("The numbers don't add up")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mark as OK" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/flags/3/resolve",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("rejects a file with a reason", async () => {
    const fetchMock = setup();
    renderAt("/review/REF-2026-000005");
    fireEvent.click(await screen.findByRole("button", { name: "Reject file" }));

    fireEvent.click(screen.getByLabelText("Bad scan or unreadable"));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(dialog.querySelector("button:last-of-type")!);

    await waitFor(() =>
      expect(sentBody(fetchMock, "POST")).toEqual({ reason: "Bad scan or unreadable" }),
    );
  });

  it("shows one tab per receipt when a file holds several", async () => {
    const run = file().runs[0]!;
    const detail = file({
      runs: [
        {
          ...run,
          result: [
            { ...run.result![0]!, vendor: "Annapurna Tiffin", receipt_number: "R-101" },
            { ...run.result![0]!, vendor: "Annapurna Tiffin", receipt_number: "R-102" },
          ],
        },
      ],
    });
    setup(detail);
    renderAt("/review/REF-2026-000005");

    const second = await screen.findByRole("tab", { name: "Receipt 2" });
    expect((screen.getByLabelText("Receipt no.") as HTMLInputElement).value).toBe("R-101");
    fireEvent.click(second);
    expect((screen.getByLabelText("Receipt no.") as HTMLInputElement).value).toBe("R-102");
  });
});

describe("Review page with an AI result", () => {
  it("shows the AI result next to the library's, marks differences and copies with Use this", async () => {
    const libraryRun = file().runs[0]!;
    const detail = file({
      status: "flagged",
      error: "The readers disagree. Choose on the Review page.",
      runs: [
        {
          ...libraryRun,
          id: 10,
          parser: "ai",
          provider: "anthropic",
          model: "claude-sonnet-5",
          ai_approved_by: "local user",
          ai_approved_at: NOW,
          accepted: false,
          result: [
            {
              ...libraryRun.result![0]!,
              vendor: "Raju Paints",
              receipt_date: "2026-08-20",
              total: "210.00",
            },
          ],
        },
        libraryRun,
      ],
    });
    mockApi((url, method) => {
      if (url === "/api/health/ready") return { body: READY };
      if (url === "/api/categories") return { body: CATEGORIES };
      if (url === "/api/ai/usage")
        return {
          body: { enabled: true, daily_cap: 50, used_today: 1, remaining: 49, providers: [] },
        };
      if (url === `/api/files/${detail.ref_no}` && method === "GET") return { body: detail };
    });
    renderAt("/review/REF-2026-000005");

    expect(await screen.findByText("AI result · Claude")).toBeTruthy();
    expect(screen.getAllByText("Differs").length).toBe(1); // vendor; the library had no date or total
    expect(screen.getByText("Raju Paints")).toBeTruthy();

    const useButtons = screen.getAllByRole("button", { name: "Use this" });
    fireEvent.click(useButtons[1]!); // the AI's vendor
    expect((screen.getByLabelText("Vendor") as HTMLInputElement).value).toBe("Raju Paints");
    expect(screen.getByRole("button", { name: "Try AI again…" })).toBeTruthy();
  });

  it("offers AI on a file that needs review", async () => {
    setup();
    renderAt("/review/REF-2026-000005");
    expect(await screen.findByRole("button", { name: "Extract with AI…" })).toBeTruthy();
  });
});
