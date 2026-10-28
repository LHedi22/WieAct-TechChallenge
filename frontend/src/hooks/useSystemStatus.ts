import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

/** Provider + offline demo mode; refreshed every minute so slot boundaries show up. */
export function useSystemStatus() {
  return useQuery({
    queryKey: ["system-status"],
    queryFn: api.systemStatus,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
