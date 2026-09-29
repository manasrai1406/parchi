import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, mockApi, READY, renderAt } from "@/test/render";

const CATEGORIES = [
  { id: 1, name: "Fuel", builtin: true, in_use: 4 },
  { id: 9, name: "Medical", builtin: false, in_use: 0 },
  { id: 10, name: "Client gifts", builtin: false, in_use: 2 },
];

function setup(me: object = ADMIN) {
  return mockApi((url, method) => {
    if (url === "/api/health/ready") return { body: READY };
    if (url === "/api/categories" && method === "GET") return { body: CATEGORIES };
    if (url === "/api/categories" && method === "POST") {
      return { status: 201, body: { id: 11, name: "Travel abroad", builtin: false, in_use: 0 } };
    }
    if (url.startsWith("/api/categories/") && method === "PATCH") return { body: CATEGORIES[1] };
    if (url.startsWith("/api/categories/") && method === "DELETE") return { status: 204 };
  }, me);
}

function calls(fetchMock: ReturnType<typeof setup>, method: string) {
  return fetchMock.mock.calls
    .filter(([, init]) => init?.method === method)
    .map(([url, init]) => ({
      url: String(url),
      body: init?.body ? JSON.parse(String(init.body)) : null,
    }));
}

function row(name: string): HTMLElement {
  return screen.getByText(name).closest("[role=row]") as HTMLElement;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Categories page", () => {
  it("lists built-in and custom categories with what uses them", async () => {
    setup();
    renderAt("/categories");

    await screen.findByText("Medical");
    expect(within(row("Fuel")).getByText("Built-in")).toBeTruthy();
    expect(within(row("Fuel")).queryByRole("button", { name: /Rename|Delete/ })).toBeNull();
    expect(within(row("Medical")).getByText("Not used")).toBeTruthy();
    expect(within(row("Client gifts")).getByText("2 receipts or vendors")).toBeTruthy();
    const inUse = within(row("Client gifts")).getByRole("button", { name: "Delete Client gifts" });
    expect((inUse as HTMLButtonElement).disabled).toBe(true);
  });

  it("adds, renames and deletes custom categories", async () => {
    const fetchMock = setup();
    renderAt("/categories");
    await screen.findByText("Medical");

    fireEvent.change(screen.getByLabelText("New category name"), {
      target: { value: "Travel abroad" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add category" }));
    await waitFor(() =>
      expect(calls(fetchMock, "POST")).toEqual([
        { url: "/api/categories", body: { name: "Travel abroad" } },
      ]),
    );

    fireEvent.click(screen.getByRole("button", { name: "Rename Medical" }));
    fireEvent.change(screen.getByLabelText("New name for Medical"), {
      target: { value: "Medical and health" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls(fetchMock, "PATCH")).toEqual([
        { url: "/api/categories/9", body: { name: "Medical and health" } },
      ]),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Delete Medical" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }),
    );
    await waitFor(() =>
      expect(calls(fetchMock, "DELETE")).toEqual([{ url: "/api/categories/9", body: null }]),
    );
  });

  it("lets viewers look but not change anything", async () => {
    setup({ ...ADMIN, role: "viewer" });
    renderAt("/categories");
    await screen.findByText("Medical");
    expect(screen.queryByLabelText("New category name")).toBeNull();
    expect(screen.queryByRole("button", { name: /Rename|Delete/ })).toBeNull();
  });
});
