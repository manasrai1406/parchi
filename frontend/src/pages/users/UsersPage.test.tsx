import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, mockApi, READY, renderAt } from "@/test/render";

const USERS = [
  {
    id: 1,
    username: "admin",
    display_name: "Asha Admin",
    role: "admin",
    active: true,
    must_change_password: false,
    last_login_at: "2026-09-28T09:00:00Z",
    created_at: "2026-09-01T09:00:00Z",
  },
  {
    id: 2,
    username: "priya",
    display_name: "Priya Sharma",
    role: "viewer",
    active: true,
    must_change_password: true,
    last_login_at: null,
    created_at: "2026-09-20T09:00:00Z",
  },
];

function setup(me: object = ADMIN) {
  return mockApi((url, method) => {
    if (url === "/api/health/ready") return { body: READY };
    if (url === "/api/users" && method === "GET") return { body: USERS };
    if (url === "/api/users" && method === "POST") return { status: 201, body: USERS[1] };
    if (url.startsWith("/api/users/")) return { body: USERS[1] };
  }, me);
}

function sent(fetchMock: ReturnType<typeof setup>, method: string) {
  return fetchMock.mock.calls
    .filter(([, init]) => init?.method === method)
    .map(([url, init]) => ({ url: String(url), body: JSON.parse(String(init?.body)) }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Users page", () => {
  it("lists accounts, and does not let admins demote or deactivate themselves", async () => {
    setup();
    renderAt("/users");

    const priya = (await screen.findByText("Priya Sharma")).closest("[role=row]") as HTMLElement;
    expect(within(priya).getByText("Password to set")).toBeTruthy();
    expect(within(priya).getByText("Never")).toBeTruthy();
    expect(within(priya).getByRole("button", { name: "Deactivate" })).toBeTruthy();

    const mine = screen.getByText("(you)").closest("[role=row]") as HTMLElement;
    expect(within(mine).queryByRole("combobox")).toBeNull();
    expect(within(mine).queryByRole("button", { name: "Deactivate" })).toBeNull();
  });

  it("changes a role straight away", async () => {
    const fetchMock = setup();
    renderAt("/users");
    fireEvent.change(await screen.findByLabelText("Role for priya"), {
      target: { value: "reviewer" },
    });
    await waitFor(() =>
      expect(sent(fetchMock, "PATCH")).toEqual([
        { url: "/api/users/2", body: { role: "reviewer" } },
      ]),
    );
  });

  it("adds a user with a temporary password", async () => {
    const fetchMock = setup();
    renderAt("/users");
    fireEvent.click(await screen.findByRole("button", { name: "Add user" }));

    const dialog = screen.getByRole("dialog", { name: "Add a user" });
    fireEvent.change(within(dialog).getByLabelText(/Username/), { target: { value: "Rahul.K" } });
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Rahul Kumar" } });
    fireEvent.change(within(dialog).getByLabelText("Role"), { target: { value: "viewer" } });
    fireEvent.change(within(dialog).getByLabelText(/Temporary password/), {
      target: { value: "short" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add user" }));
    expect(within(dialog).getByRole("alert").textContent).toContain("at least 10");
    expect(sent(fetchMock, "POST")).toEqual([]);

    fireEvent.change(within(dialog).getByLabelText(/Temporary password/), {
      target: { value: "welcome to parchi" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add user" }));
    await waitFor(() =>
      expect(sent(fetchMock, "POST")).toEqual([
        {
          url: "/api/users",
          body: {
            username: "Rahul.K",
            display_name: "Rahul Kumar",
            role: "viewer",
            temporary_password: "welcome to parchi",
          },
        },
      ]),
    );
  });

  it("asks before deactivating someone", async () => {
    const fetchMock = setup();
    renderAt("/users");
    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Deactivate" }),
    );
    await waitFor(() =>
      expect(sent(fetchMock, "PATCH")).toEqual([{ url: "/api/users/2", body: { active: false } }]),
    );
  });

  it("is for admins only", async () => {
    setup({ ...ADMIN, role: "reviewer" });
    renderAt("/users");
    expect(await screen.findByText("Only admins can manage users.")).toBeTruthy();
  });
});
