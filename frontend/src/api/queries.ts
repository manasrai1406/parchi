import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiDelete, apiGet, type Schemas } from "./client";

export type FileStatus = Schemas["FileSummary"]["status"];
export type FileSummary = Schemas["FileSummary"];

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
  page: number;
  pageSize: number;
};

export function useFiles({ status, q, page, pageSize }: FileFilters) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (status) params.set("status", status);
  if (q) params.set("q", q);

  return useQuery({
    queryKey: ["files", { status, q, page, pageSize }],
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
