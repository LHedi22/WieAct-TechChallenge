import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

/** Today's challenges (GET /api/daily); polled so progress and the AI plan show up. */
export function useDaily() {
  return useQuery({ queryKey: ["daily"], queryFn: api.daily, refetchInterval: 30_000 });
}
