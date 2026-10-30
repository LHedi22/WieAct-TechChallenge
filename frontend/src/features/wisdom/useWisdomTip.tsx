import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "@/api/client";
import { WisdomTipBody } from "./WisdomTip";

/** Tips of this world (this course first), or undefined when the class has none yet. */
export function useWisdomTip(worldId: string, courseId?: string): ReactNode | undefined {
  const tips = useQuery({
    queryKey: ["wisdom", worldId],
    queryFn: () => api.wisdom(worldId),
    enabled: Boolean(worldId),
    staleTime: 60_000,
  }).data?.tips;
  if (!tips?.length) return undefined;
  const ordered = courseId
    ? [
        ...tips.filter((x) => x.course_id === courseId),
        ...tips.filter((x) => x.course_id !== courseId),
      ]
    : tips;
  return <WisdomTipBody tips={ordered} />;
}
