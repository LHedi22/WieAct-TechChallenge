import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export function usePool(worldId: string) {
  return useQuery({
    queryKey: ["pool", worldId],
    queryFn: () => api.pool(worldId),
    enabled: !!worldId,
  });
}
