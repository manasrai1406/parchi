import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "@/test/render";

import { AiApprovalDialog } from "./AiApprovalDialog";

const FILE = { ref_no: "REF-2026-000005", original_name: "tea_stall.png", kind: "image" as const };
const SHEET = { ref_no: "REF-2026-000006", original_name: "march.xlsx", kind: "excel" as const };

function usage(extra: Record<string, unknown> = {}) {
  return {
    enabled: true,
    daily_cap: 50,
    used_today: 12,
    remaining: 38,
    providers: [
      { provider: "anthropic", label: "Claude", model: "claude-sonnet-5", configured: true },
      { provider: "openai", label: "OpenAI", model: "gpt-6-sol", configured: false },
    ],
    ...extra,
  };
}

function setup(ai = usage()) {
  const fetchMock = mockApi((url, method) => {
    if (url === "/api/ai/usage") return { body: ai };
    if (method === "POST" && url.endsWith("ai-extract")) {
      return { status: 202, body: { runs: [{ file_id: 5, ref_no: FILE.ref_no, run_id: 9 }] } };
    }
  });
  const onClose = vi.fn();
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AiApprovalDialog files={[FILE]} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { fetchMock, onClose };
}

function posts(fetchMock: ReturnType<typeof setup>["fetchMock"]) {
  return fetchMock.mock.calls
    .filter(([, init]) => init?.method === "POST")
    .map(([url, init]) => ({ url: String(url), body: JSON.parse(String(init?.body)) }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AI approval dialog", () => {
  it("says what is sent where, and needs the approval ticked before anything is sent", async () => {
    const { fetchMock, onClose } = setup();

    expect(await screen.findByText("Extract this file with AI?")).toBeTruthy();
    expect(screen.getByText(/tea_stall.png, goes as it is to the provider/)).toBeTruthy();
    expect(await screen.findByText("Uses 1 of your 38 remaining approvals today.")).toBeTruthy();
    const approve = screen.getByRole("button", {
      name: "Approve and extract",
    }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);

    fireEvent.click(screen.getByLabelText("I approve sending this file to the selected provider."));
    fireEvent.click(approve);

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(posts(fetchMock)).toEqual([
      {
        url: "/api/files/REF-2026-000005/ai-extract",
        body: { provider: "anthropic", approved: true },
      },
    ]);
  });

  it("does not offer a provider without an API key", async () => {
    setup();
    const openai = (await screen.findByDisplayValue("openai")) as HTMLInputElement;
    expect(openai.disabled).toBe(true);
    expect(screen.getByText("No API key set")).toBeTruthy();
  });

  it("explains when AI is switched off and sends nothing", async () => {
    const { fetchMock } = setup(usage({ enabled: false }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/AI is switched off/)).toBeTruthy();
    expect((screen.getByLabelText(/I approve/) as HTMLInputElement).disabled).toBe(true);
    expect(posts(fetchMock)).toEqual([]);
  });

  it("explains when no provider has a key", async () => {
    const none = usage();
    none.providers = none.providers.map((p) => ({ ...p, configured: false }));
    setup(none);
    expect(await screen.findByText(/No AI provider has an API key yet/)).toBeTruthy();
  });

  it("stops at the daily limit", async () => {
    setup(usage({ remaining: 0 }));
    expect(await screen.findByText("Today's limit allows 0 more AI reads.")).toBeTruthy();
  });

  it("approves several files in one request", async () => {
    const fetchMock = mockApi((url, method) => {
      if (url === "/api/ai/usage") return { body: usage() };
      if (method === "POST") return { status: 202, body: { runs: [] } };
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AiApprovalDialog files={[FILE, SHEET]} onClose={() => {}} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Extract 2 files with AI?")).toBeTruthy();
    expect(screen.getByText(/spreadsheets as text/)).toBeTruthy();
    fireEvent.click(
      screen.getByLabelText("I approve sending these 2 files to the selected provider."),
    );
    fireEvent.click(screen.getByRole("button", { name: "Approve and extract" }));

    await waitFor(() => expect(posts(fetchMock).length).toBe(1));
    expect(posts(fetchMock)[0]).toEqual({
      url: "/api/files/ai-extract",
      body: { files: [FILE.ref_no, SHEET.ref_no], provider: "anthropic", approved: true },
    });
  });
});
