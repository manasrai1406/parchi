import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, READY, renderAt } from "@/test/render";

const ROW = {
  ref_no: "REF-2026-000210-01",
  file_ref_no: "REF-2026-000210",
  receipt_date: "2026-08-03",
  vendor: "Sector 12 Fuel Station",
  receipt_number: "SF-20431",
  category: "Fuel",
  subtotal: null,
  tax: null,
  total: "2400.00",
};

function page(extra: Record<string, unknown> = {}) {
  return {
    items: [ROW],
    count: 1,
    sum_total: "2400.00",
    average_total: "2400.00",
    page: 1,
    page_size: 50,
    date_from: "2026-04-01",
    date_to: "2026-09-26",
    waiting_for_review: 5,
    ...extra,
  };
}

const ASKED = {
  question: "fuel in August",
  understood_as: [
    { label: "Category", value: "Fuel" },
    { label: "Dates", value: "1 Aug 2026 to 31 Aug 2026" },
    { label: "Status", value: "Parsed or Resolved" },
  ],
  ignored: ["urgently"],
  filters: {
    date_from: "2026-08-01",
    date_to: "2026-08-31",
    vendor: null,
    category_id: 1,
    min_total: null,
    max_total: null,
    sort: "date",
    limit: null,
    page: 1,
  },
  sql: "SELECT receipt_view.receipt_date FROM receipt_view WHERE receipt_view.category_id = 1;",
  result: page({ date_from: "2026-08-01", date_to: "2026-08-31" }),
};

function setup(ask: { status?: number; body: unknown } = { body: ASKED }) {
  return mockApi((url, method) => {
    if (url === "/api/health/ready") return { body: READY };
    if (url.startsWith("/api/receipts?") || url === "/api/receipts") return { body: page() };
    if (url === "/api/vendors")
      return { body: ["Ring Road Petrol Pump", "Sector 12 Fuel Station"] };
    if (url === "/api/categories") {
      return {
        body: [
          { id: 1, name: "Fuel", builtin: true, in_use: 3 },
          { id: 3, name: "Food", builtin: true, in_use: 1 },
        ],
      };
    }
    if (method === "POST" && url === "/api/query/ask") return ask;
  });
}

function receiptCalls(fetchMock: ReturnType<typeof setup>): URLSearchParams[] {
  return fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.startsWith("/api/receipts"))
    .map((url) => new URLSearchParams(url.split("?")[1] ?? ""));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Query page", () => {
  it("opens on this financial year with totals, rows and what is left out", async () => {
    const fetchMock = setup();
    renderAt("/query");

    expect(await screen.findByRole("cell", { name: "Sector 12 Fuel Station" })).toBeTruthy();
    expect(receiptCalls(fetchMock)[0]!.toString()).toBe(""); // the server picks the dates
    expect((screen.getByLabelText("From") as HTMLInputElement).value).toBe("2026-04-01");
    expect((screen.getByLabelText("To") as HTMLInputElement).value).toBe("2026-09-26");
    const summary = screen.getByRole("region", { name: "Summary" });
    expect(within(summary).getAllByText("₹2,400.00")).toHaveLength(2); // total and average
    expect(within(summary).getByText("5 files are waiting for review")).toBeTruthy();
    const link = screen.getByRole("link", { name: "REF-2026-000210-01" });
    expect(link.getAttribute("href")).toBe("/review/REF-2026-000210");
  });

  it("shows how a question was read, the SQL that ran, and fills the filters", async () => {
    const fetchMock = setup();
    renderAt("/query");
    await screen.findByRole("cell", { name: "Sector 12 Fuel Station" });

    fireEvent.change(screen.getByLabelText("Ask about your receipts"), {
      target: { value: "fuel in August urgently" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Category: Fuel")).toBeTruthy();
    expect(screen.getByText("1 Aug 2026 to 31 Aug 2026")).toBeTruthy();
    expect(screen.getByText("Status: Parsed or Resolved")).toBeTruthy();
    expect(screen.getByText(/Not understood, so left out: “urgently”/)).toBeTruthy();
    expect(screen.getByText(/category_id = 1;/)).toBeTruthy();
    expect((screen.getByLabelText("From") as HTMLInputElement).value).toBe("2026-08-01");
    expect((screen.getByLabelText("Category") as HTMLSelectElement).value).toBe("1");
    const posted = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(posted?.[1]?.body))).toEqual({ question: "fuel in August urgently" });
    // The answer carried the first page, so it is not fetched again.
    expect(receiptCalls(fetchMock).some((p) => p.get("category_id") === "1")).toBe(false);
    const csv = screen.getByRole("link", { name: "Export CSV" }).getAttribute("href");
    expect(csv).toContain("date_from=2026-08-01");
    expect(csv).toContain("category_id=1");
  });

  it("says when a question cannot be read", async () => {
    setup({
      status: 422,
      body: {
        code: "question_not_understood",
        message: "Could not understand that question.",
        request_id: null,
      },
    });
    renderAt("/query");
    fireEvent.change(await screen.findByLabelText("Ask about your receipts"), {
      target: { value: "hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("Could not understand that question.")).toBeTruthy();
  });

  it("re-runs as soon as a date changes, and refuses From after To", async () => {
    const fetchMock = setup();
    renderAt("/query");
    await screen.findByRole("cell", { name: "Sector 12 Fuel Station" });

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-08-01" } });
    await waitFor(() =>
      expect(
        receiptCalls(fetchMock).some(
          (p) => p.get("date_from") === "2026-08-01" && p.get("date_to") === "2026-09-26",
        ),
      ).toBe(true),
    );

    const before = receiptCalls(fetchMock).length;
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } });
    expect(screen.getByText("From cannot be later than To.")).toBeTruthy();
    expect(receiptCalls(fetchMock).length).toBe(before);
  });

  it("applies vendor, category and amounts together", async () => {
    const fetchMock = setup();
    renderAt("/query");
    await screen.findByRole("option", { name: "Ring Road Petrol Pump" });

    fireEvent.change(screen.getByLabelText("Min amount"), { target: { value: "900" } });
    fireEvent.change(screen.getByLabelText("Max amount"), { target: { value: "500" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByText("The minimum amount cannot be more than the maximum.")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Max amount"), { target: { value: "1,500" } });
    fireEvent.change(screen.getByLabelText("Vendor"), {
      target: { value: "Ring Road Petrol Pump" },
    });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => {
      const last = receiptCalls(fetchMock).at(-1)!;
      expect(Object.fromEntries(last)).toEqual({
        vendor: "Ring Road Petrol Pump",
        category_id: "1",
        min_total: "900",
        max_total: "1500",
      });
    });
  });

  it("pages through the results 50 at a time", async () => {
    const fetchMock = mockApi((url) => {
      if (url === "/api/health/ready") return { body: READY };
      if (url.startsWith("/api/receipts")) return { body: page({ count: 120 }) };
      if (url === "/api/vendors" || url === "/api/categories") return { body: [] };
    });
    renderAt("/query");
    expect(await screen.findByText("1 / 3 pages")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(receiptCalls(fetchMock).at(-1)!.get("page")).toBe("2"));
  });
});
