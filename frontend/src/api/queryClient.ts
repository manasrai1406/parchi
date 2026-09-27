import { MutationCache, QueryCache, QueryClient, type DefaultOptions } from "@tanstack/react-query";

import { ME_KEY } from "@/auth/session";

import { ApiError } from "./client";

/**
 * The app's query client. When any request says the session has ended (401), who is
 * logged in is cleared, and the Layout sends the person to the login page.
 */
export function createQueryClient(defaultOptions?: DefaultOptions): QueryClient {
  const onError = (error: unknown) => {
    if (error instanceof ApiError && error.status === 401) {
      client.setQueryData(ME_KEY, null);
    }
  };
  const client = new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions,
  });
  return client;
}
