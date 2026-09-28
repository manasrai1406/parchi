import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ADMIN, mockApi, READY, renderAt } from "@/test/render";

const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 25 };

function api(
  ready: { status: number; body: unknown } = { status: 200, body: READY },
  me: object | null = ADMIN,
) {
  return mockApi((url) => {
    if (url === "/api/health/ready") return ready;
    if (url.startsWith("/api/files?")) return { body: EMPTY_PAGE };
  }, me);
}

function navLinks(nav: HTMLElement): (string | null)[] {
  return Array.from(nav.querySelectorAll("a")).map((a) => a.textContent);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("app shell", () => {
  it("shows the pages in the sidebar and marks the current one", async () => {
    api();
    renderAt("/files");

    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(navLinks(nav)).toEqual(["Upload", "Files", "Review", "Query", "Users"]);
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

describe("login", () => {
  it("sends someone who is not logged in to the login page, and back after logging in", async () => {
    const fetchMock = mockApi((url, method) => {
      if (url === "/api/health/ready") return { body: READY };
      if (url.startsWith("/api/files?")) return { body: EMPTY_PAGE };
      if (method === "POST" && url === "/api/auth/login") return { body: ADMIN };
    }, null);
    const router = renderAt("/query");

    expect(await screen.findByRole("heading", { name: "Log in" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/login");
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: " admin " } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a long password" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/query"));
    const posted = fetchMock.mock.calls.find(([url]) => String(url) === "/api/auth/login");
    expect(JSON.parse(String(posted?.[1]?.body))).toEqual({
      username: "admin",
      password: "a long password",
    });
  });

  it("shows why a login failed", async () => {
    mockApi((url, method) => {
      if (method === "POST" && url === "/api/auth/login") {
        return {
          status: 401,
          body: { code: "login_failed", message: "Wrong username or password.", request_id: null },
        };
      }
    }, null);
    renderAt("/login");
    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "y" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByText("Wrong username or password.")).toBeTruthy();
  });

  it("asks for a new password before anything else when it was set by an admin", async () => {
    api(undefined, { ...ADMIN, must_change_password: true });
    const router = renderAt("/files");
    expect(await screen.findByRole("heading", { name: "Choose your own password" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/change-password");
  });

  it("shows viewers only the pages they can use", async () => {
    api(undefined, { ...ADMIN, username: "vik", display_name: "Vik", role: "viewer" });
    renderAt("/files");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(navLinks(nav)).toEqual(["Files", "Review", "Query"]);
    expect(screen.getByText("Viewer", { exact: false })).toBeTruthy();
  });
});

describe("sign-up", () => {
  const VIEWER = { ...ADMIN, id: 7, username: "neha", display_name: "Neha Gupta", role: "viewer" };

  function signupApi(signup: boolean) {
    return mockApi((url, method) => {
      if (url === "/api/health/ready") return { body: READY };
      if (url === "/api/auth/options") return { body: { signup } };
      if (url.startsWith("/api/files?")) return { body: EMPTY_PAGE };
      if (method === "POST" && url === "/api/auth/signup") return { status: 201, body: VIEWER };
    }, null);
  }

  it("lets someone create their own account and logs them in", async () => {
    const fetchMock = signupApi(true);
    const router = renderAt("/login");

    fireEvent.click(await screen.findByRole("link", { name: "Create an account" }));
    expect(await screen.findByRole("heading", { name: "Create an account" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "neha" } });
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Neha Gupta" } });
    fireEvent.change(screen.getByLabelText(/^Password \(/), {
      target: { value: "a long password" },
    });
    fireEvent.change(screen.getByLabelText("Password again"), {
      target: { value: "different one" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByRole("alert").textContent).toBe("The two passwords do not match.");

    fireEvent.change(screen.getByLabelText("Password again"), {
      target: { value: "a long password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/files"));
    const posted = fetchMock.mock.calls.find(([url]) => String(url) === "/api/auth/signup");
    expect(JSON.parse(String(posted?.[1]?.body))).toEqual({
      username: "neha",
      display_name: "Neha Gupta",
      password: "a long password",
    });
  });

  it("does not offer sign-up when it is turned off", async () => {
    signupApi(false);
    renderAt("/login");
    expect(await screen.findByRole("heading", { name: "Log in" })).toBeTruthy();
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Create an account" })).toBeNull(),
    );
    cleanup();
    renderAt("/signup");
    expect(await screen.findByText("Sign-up is turned off here.")).toBeTruthy();
  });
});
