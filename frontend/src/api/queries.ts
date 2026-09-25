import { useQuery } from "@tanstack/react-query";

import { apiGet, type Schemas } from "./client";

export function useReadiness() {
  return useQuery({
    queryKey: ["health", "ready"],
    queryFn: () => apiGet<Schemas["ReadyResponse"]>("/health/ready"),
    refetchInterval: 15_000,
    retry: false,
  });
}
