import { z } from "zod";

import type { FileDetail, ReceiptIn } from "@/api/queries";
import type { Schemas } from "@/api/client";

type Extracted = Schemas["ReceiptSchema"];

/** Form values are strings, as typed; they become the API's shape on save. */
export type ItemValues = {
  description: string;
  quantity: string;
  unit_price: string;
  amount: string;
};

export type ReceiptValues = {
  vendor: string;
  receipt_number: string;
  receipt_date: string;
  subtotal: string;
  tax: string;
  total: string;
  category_id: string;
  line_items: ItemValues[];
};

export type FormValues = { receipts: ReceiptValues[] };

const text = (value: string | number | null | undefined): string =>
  value === null || value === undefined ? "" : String(value);

export const EMPTY_ITEM: ItemValues = { description: "", quantity: "", unit_price: "", amount: "" };

const EMPTY_RECEIPT: ReceiptValues = {
  vendor: "",
  receipt_number: "",
  receipt_date: "",
  subtotal: "",
  tax: "",
  total: "",
  category_id: "",
  line_items: [],
};

/** What the library reader found for each receipt, for comparison. */
export function libraryResults(file: FileDetail): Extracted[] {
  const run = file.runs.find((r) => r.parser !== "manual" && r.parser !== "ai" && r.result);
  return run?.result ?? [];
}

/** The latest AI read, if a person approved one (runs arrive newest first). */
export function aiRun(file: FileDetail) {
  return file.runs.find((r) => r.parser === "ai" && r.finished_at);
}

/** A field of an extracted receipt as the form would hold it, for comparing and copying. */
export function fieldValue(
  receipt: Extracted | undefined,
  field: "vendor" | "receipt_number" | "receipt_date" | "subtotal" | "tax" | "total",
): string {
  return receipt ? text(receipt[field]) : "";
}

/** Start from the stored receipts; if none, from what the reader found; else blank. */
export function initialValues(file: FileDetail): FormValues {
  if (file.receipts.length > 0) {
    return {
      receipts: file.receipts.map((r) => ({
        vendor: r.vendor,
        receipt_number: text(r.receipt_number),
        receipt_date: r.receipt_date,
        subtotal: text(r.subtotal),
        tax: text(r.tax),
        total: text(r.total),
        category_id: text(r.category_override_id ?? r.category_auto_id),
        line_items: r.line_items.map((i) => ({
          description: i.description,
          quantity: text(i.quantity),
          unit_price: text(i.unit_price),
          amount: text(i.amount),
        })),
      })),
    };
  }
  const found = file.runs.find((r) => r.result && r.result.length > 0)?.result;
  if (found) {
    return {
      receipts: found.map((r) => ({
        vendor: text(r.vendor),
        receipt_number: text(r.receipt_number),
        receipt_date: text(r.receipt_date),
        subtotal: text(r.subtotal),
        tax: text(r.tax),
        total: text(r.total),
        category_id: "",
        line_items: (r.line_items ?? []).map((i) => ({
          description: i.description,
          quantity: text(i.quantity),
          unit_price: text(i.unit_price),
          amount: text(i.amount),
        })),
      })),
    };
  }
  return { receipts: [{ ...EMPTY_RECEIPT }] };
}

const MONEY = /^-?\d{1,10}(\.\d{1,2})?$/;
const QUANTITY = /^\d{1,9}(\.\d{1,3})?$/;
const UNIT_PRICE = /^\d{1,10}(\.\d{1,4})?$/;

const optional = (pattern: RegExp, message: string) =>
  z
    .string()
    .trim()
    .refine((v) => v === "" || pattern.test(v.replace(/,/g, "")), message);

const itemSchema = z.object({
  description: z.string().trim().min(1, "Describe the item."),
  quantity: optional(QUANTITY, "Up to 3 decimal places."),
  unit_price: optional(UNIT_PRICE, "Up to 4 decimal places."),
  amount: z
    .string()
    .trim()
    .refine((v) => MONEY.test(v.replace(/,/g, "")), "Enter an amount, e.g. 120.00."),
});

const receiptSchema = z.object({
  vendor: z.string().trim().min(1, "The vendor is required."),
  receipt_number: z.string().trim().max(64, "At most 64 characters."),
  receipt_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "The date is required."),
  subtotal: optional(MONEY, "Enter an amount, e.g. 1000.00."),
  tax: optional(MONEY, "Enter an amount, e.g. 180.00."),
  total: z
    .string()
    .trim()
    .refine((v) => MONEY.test(v.replace(/,/g, "")), "The total is required, e.g. 1180.00."),
  category_id: z.string(),
  line_items: z.array(itemSchema),
});

export const formSchema = z.object({ receipts: z.array(receiptSchema).min(1) });

const money = (value: string): string | null => {
  const clean = value.trim().replace(/,/g, "");
  return clean === "" ? null : clean;
};

/** Checked form values in the API's shape. */
export function toReceiptsIn(values: FormValues): ReceiptIn[] {
  return values.receipts.map((r) => ({
    vendor: r.vendor.trim(),
    receipt_number: r.receipt_number.trim() || null,
    receipt_date: r.receipt_date,
    subtotal: money(r.subtotal),
    tax: money(r.tax),
    total: money(r.total) ?? "0",
    category_id: r.category_id ? Number(r.category_id) : null,
    line_items: r.line_items.map((i) => ({
      description: i.description.trim(),
      quantity: money(i.quantity),
      unit_price: money(i.unit_price),
      amount: money(i.amount) ?? "0",
    })),
  }));
}

/** Whether the items add up to the subtotal or total within ₹1 (D-029), for the hint. */
export function itemsAddUp(receipt: ReceiptValues): { sum: number; ok: boolean } | null {
  if (receipt.line_items.length === 0) return null;
  const sum = receipt.line_items.reduce(
    (total, item) => total + (Number(item.amount.replace(/,/g, "")) || 0),
    0,
  );
  const targets = [receipt.subtotal, receipt.total]
    .map((v) => Number(v.replace(/,/g, "")))
    .filter((v) => v !== 0 && Number.isFinite(v));
  return { sum, ok: targets.some((target) => Math.abs(target - sum) <= 1) };
}
