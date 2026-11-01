import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { WisdomTip } from "@/api/client";
import { api } from "@/api/client";
import type { LoadingTip } from "@/components";
import { GeneralTip, WisdomTipBody } from "./WisdomTip";

/** This course's Class Wisdom tips only (never another course's). */
export function useClassTips(worldId: string, courseId?: string): WisdomTip[] {
  const tips = useQuery({
    queryKey: ["wisdom", worldId],
    queryFn: () => api.wisdom(worldId),
    enabled: Boolean(worldId),
    staleTime: 60_000,
  }).data?.tips;
  return (tips ?? []).filter((x) => x.course_id === courseId);
}

/** The loading-screen tip: this course's Class Wisdom, or a general study tip when the course
 * has none yet. */
export function useWisdomTip(worldId: string, courseId?: string): LoadingTip {
  const { t } = useTranslation();
  const tips = useClassTips(worldId, courseId);
  if (tips.length) return { title: t("wisdom.title"), body: <WisdomTipBody tips={tips} /> };
  return { title: t("wisdom.general.title"), body: <GeneralTip /> };
}
