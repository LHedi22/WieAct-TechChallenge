import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Me } from "@/api/client";

/** The signed-in user, or null when signed out (401). */
export function useMe() {
  return useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: api.session, // 200 with null when signed out: no 401 noise on public pages
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
