import { describe, expect, it } from "vitest";

import { extensionLabel, formatBytes, formatUploaded } from "./format";

describe("formatBytes", () => {
  it.each([
    [512, "512 B"],
    [184 * 1024, "184 KB"],
    [2.4 * 1024 * 1024, "2.4 MB"],
  ])("%d bytes is %s", (bytes, text) => {
    expect(formatBytes(bytes)).toBe(text);
  });
});

describe("formatUploaded", () => {
  const now = new Date(2026, 8, 26, 12, 0);

  it("says Today and Yesterday for recent uploads", () => {
    expect(formatUploaded(new Date(2026, 8, 26, 9, 5).toISOString(), now)).toBe("Today, 09:05");
    expect(formatUploaded(new Date(2026, 8, 25, 22, 41).toISOString(), now)).toBe(
      "Yesterday, 22:41",
    );
  });

  it("shows the date for older uploads, and the year only when it differs", () => {
    expect(formatUploaded(new Date(2026, 8, 12, 16, 40).toISOString(), now)).toBe("12 Sept, 16:40");
    expect(formatUploaded(new Date(2025, 11, 31, 8, 0).toISOString(), now)).toBe(
      "31 Dec 2025, 08:00",
    );
  });
});

describe("extensionLabel", () => {
  it.each([
    ["inv_0421.pdf", "PDF"],
    ["march.expenses.xlsx", "XLSX"],
    ["noextension", "FILE"],
  ])("%s is %s", (name, label) => {
    expect(extensionLabel(name)).toBe(label);
  });
});
