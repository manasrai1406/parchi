import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiGet, apiSend, type Schemas } from "@/api/client";

export type Me = Schemas["MeOut"];
export type Role = Schemas["UserRole"];

export const ME_KEY = ["auth", "me"] as const;

const RANK: Record<Role, number> = { viewer: 0, reviewer: 1, admin: 2 };

export const ROLE_LABELS: Record<Role, string> = {
  viewer: "Viewer",
  reviewer: "Reviewer",
  admin: "Admin",
};

/** Whether a user's role includes another (D-044: each role includes the ones below it). */
export function can(user: Pick<Me, "role"> | null | undefined, role: Role): boolean {
  return user ? RANK[user.role] >= RANK[role] : false;
}

/** Who is logged in: null when nobody is. */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: async (): Promise<Me | null> => {
      try {
        return await apiGet<Me>("/auth/me");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

/** The logged-in user, inside pages the Layout only shows to someone logged in. */
export function useCurrentUser(): Me | null {
  return useMe().data ?? null;
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (details: Schemas["LoginIn"]) => apiSend<Me>("POST", "/auth/login", details),
    onSuccess: (me) => {
      // Nothing from a previous user's session should be shown to this one.
      queryClient.clear();
      queryClient.setQueryData(ME_KEY, me);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<void>("POST", "/auth/logout"),
    onSettled: () => {
      queryClient.clear();
      queryClient.setQueryData(ME_KEY, null);
    },
  });
}

export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["PasswordChangeIn"]) => apiSend<Me>("PUT", "/auth/password", body),
    onSuccess: (me) => queryClient.setQueryData(ME_KEY, me),
  });
}
