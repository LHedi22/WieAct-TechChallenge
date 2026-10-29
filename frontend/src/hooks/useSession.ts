import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Me } from "@/api/client";

/** The signed-in user, or null when signed out (401). */
export function useMe() {
  return useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api.me();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useSignOut() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      qc.setQueryData(["me"], null);
      void qc.invalidateQueries();
    },
  });
}

/** Every price and reward in the UI comes from here (backend/app/core/economy.py). */
export function useEconomy() {
  return useQuery({ queryKey: ["economy"], queryFn: api.economy, staleTime: Infinity });
}

export function useWallet() {
  return useQuery({ queryKey: ["wallet"], queryFn: api.wallet, refetchInterval: 60_000 });
}
