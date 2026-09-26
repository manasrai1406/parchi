import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiDelete, apiGet, apiSend, type Schemas } from "./client";

export type FileStatus = Schemas["FileSummary"]["status"];
export type FileSummary = Schemas["FileSummary"];
export type FileDetail = Schemas["FileDetail"];
export type Category = Schemas["CategoryOut"];
export type ReceiptIn = Schemas["ReceiptIn"];

/** Statuses a worker will still change. While any file is in one, lists keep refreshing. */
export const IN_PROGRESS: readonly FileStatus[] = ["pending", "processing", "ai_processing"];

const REFRESH_MS = 5_000;

export function useReadiness() {
  return useQuery({
    queryKey: ["health", "ready"],
    queryFn: () => apiGet<Schemas["ReadyResponse"]>("/health/ready"),
    refetchInterval: 15_000,
    retry: false,
  });
}

export type FileFilters = {
  status?: FileStatus;
  q?: string;
  attention?: boolean;
  page: number;
  pageSize: number;
};

export function useFiles({ status, q, attention, page, pageSize }: FileFilters) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (status) params.set("status", status);
  if (q) params.set("q", q);
  if (attention) params.set("attention", "true");

  return useQuery({
    queryKey: ["files", { status, q, attention, page, pageSize }],
    queryFn: () => apiGet<Schemas["FilePage"]>(`/files?${params}`),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((file) => IN_PROGRESS.includes(file.status))
        ? REFRESH_MS
        : false,
  });
}

/** Every batch this upload session used, refreshed while their files are being worked on. */
export function useBatches(batchIds: number[]) {
  return useQueries({
    queries: batchIds.map((id) => ({
      queryKey: ["batches", id],
      queryFn: () => apiGet<Schemas["BatchDetail"]>(`/batches/${id}`),
      refetchInterval: (query: { state: { data?: Schemas["BatchDetail"] } }) =>
        query.state.data?.files.some((file) => IN_PROGRESS.includes(file.status))
          ? REFRESH_MS
          : false,
    })),
  });
}

export function downloadUrl(file: Pick<FileSummary, "ref_no">): string {
  return `/api/files/${encodeURIComponent(file.ref_no)}/download`;
}

/** Statuses during which a file cannot be deleted (D-019). */
export const BUSY: readonly FileStatus[] = ["processing", "ai_processing"];

export function useDeleteFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: Pick<FileSummary, "ref_no">) =>
      apiDelete(`/files/${encodeURIComponent(file.ref_no)}`),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["files"] }),
        queryClient.invalidateQueries({ queryKey: ["batches"] }),
      ]),
  });
}

/** Files a person should look at: needs review, flagged, or parsed with open warnings. */
export function needsAttention(file: Pick<FileSummary, "status" | "open_flags">): boolean {
  return file.status === "needs_review" || file.status === "flagged" || file.open_flags > 0;
}

export function errorReportUrl(file: Pick<FileSummary, "ref_no">): string {
  return `/api/files/${encodeURIComponent(file.ref_no)}/error-report`;
}

export const ALL_ERROR_REPORTS_URL = "/api/files/error-reports.zip";

export function useSummary() {
  return useQuery({
    queryKey: ["files", "summary"],
    queryFn: () => apiGet<Schemas["FileCounts"]>("/files/summary"),
    refetchInterval: 10_000,
  });
}

export function useFileDetail(ref: string) {
  return useQuery({
    queryKey: ["file", ref],
    queryFn: () => apiGet<FileDetail>(`/files/${encodeURIComponent(ref)}`),
    refetchInterval: (query) =>
      query.state.data && IN_PROGRESS.includes(query.state.data.status) ? REFRESH_MS : false,
  });
}

/** After any change to a file, everything that shows files is refreshed. */
function useRefreshFiles() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["files"] }),
      queryClient.invalidateQueries({ queryKey: ["file"] }),
      queryClient.invalidateQueries({ queryKey: ["batches"] }),
    ]);
}

export function useSaveReceipts(ref: string) {
  const refresh = useRefreshFiles();
  return useMutation({
    mutationFn: (receipts: ReceiptIn[]) =>
      apiSend<FileDetail>("PUT", `/files/${encodeURIComponent(ref)}/receipts`, { receipts }),
    onSuccess: refresh,
  });
}

export function useRejectFile(ref: string) {
  const refresh = useRefreshFiles();
  return useMutation({
    mutationFn: (reason: string) =>
      apiSend<FileDetail>("POST", `/files/${encodeURIComponent(ref)}/reject`, { reason }),
    onSuccess: refresh,
  });
}

export function useResolveFlag() {
  const refresh = useRefreshFiles();
  return useMutation({
    mutationFn: (flagId: number) => apiSend<Schemas["FlagOut"]>("POST", `/flags/${flagId}/resolve`),
    onSuccess: refresh,
  });
}

export function useCategories() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: () => apiGet<Category[]>("/categories"),
  });
}

export function useCreateCategory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiSend<Category>("POST", "/categories", { name }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["categories"] }),
  });
}

export type AiProvider = Schemas["AiExtractIn"]["provider"];
export type AiUsage = Schemas["AiUsage"];

/** How each provider is named on screen. */
export const AI_LABELS: Record<AiProvider, string> = {
  anthropic: "Claude",
  openai: "OpenAI",
  gemini: "Gemini",
};

/** Files the AI approval accepts (D-036): the reader failed, AI failed, or warnings remain. */
export const AI_ELIGIBLE: readonly FileStatus[] = ["needs_review", "flagged", "parsed"];

export function useAiUsage() {
  return useQuery({
    queryKey: ["ai", "usage"],
    queryFn: () => apiGet<AiUsage>("/ai/usage"),
    refetchInterval: 15_000,
  });
}

/** Approve files for an AI read. Nothing is sent before this call succeeds (hard rule 1). */
export function useApproveAi() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ refs, provider }: { refs: string[]; provider: AiProvider }) =>
      refs.length === 1
        ? apiSend<Schemas["AiRunsOut"]>(
            "POST",
            `/files/${encodeURIComponent(refs[0]!)}/ai-extract`,
            { provider, approved: true },
          )
        : apiSend<Schemas["AiRunsOut"]>("POST", "/files/ai-extract", {
            files: refs,
            provider,
            approved: true,
          }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ["files"] }),
        queryClient.invalidateQueries({ queryKey: ["file"] }),
        queryClient.invalidateQueries({ queryKey: ["ai"] }),
      ]),
  });
}

export type ReceiptPage = Schemas["ReceiptPage"];
export type AskOut = Schemas["AskOut"];
/** The Query page's filters; the page number travels separately. */
export type ReceiptFilters = Partial<Omit<Schemas["ReceiptQuery"], "page">>;

/** Filters as query parameters, leaving out the ones not set. */
export function receiptParams(filters: ReceiptFilters, page?: number): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  }
  if (page && page > 1) params.set("page", String(page));
  return params;
}

export function receiptsKey(filters: ReceiptFilters, page: number) {
  return ["receipts", filters, page] as const;
}

/** Receipts from parsed and resolved files; with no dates, the financial year to date. */
export function useReceipts(filters: ReceiptFilters, page: number) {
  return useQuery({
    queryKey: receiptsKey(filters, page),
    queryFn: () => apiGet<ReceiptPage>(`/receipts?${receiptParams(filters, page)}`),
    // Long enough that the first page an answer brought is not fetched again at once.
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });
}

export function receiptsCsvUrl(filters: ReceiptFilters): string {
  return `/api/receipts/export.csv?${receiptParams(filters)}`;
}

export function useVendors() {
  return useQuery({ queryKey: ["vendors"], queryFn: () => apiGet<string[]>("/vendors") });
}

/** A plain-English question, read by rules on the server. Nothing goes to an AI provider. */
export function useAsk() {
  return useMutation({
    mutationFn: (question: string) => apiSend<AskOut>("POST", "/query/ask", { question }),
  });
}
