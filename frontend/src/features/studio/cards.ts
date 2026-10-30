import { useTranslation } from "react-i18next";

export function cardsKey(chapterId: string, level: string) {
  return ["studio-cards", chapterId, level];
}

/** "in <1 min", "in 10 min", "in 3 days": when a card comes back after this grade. */
export function useWhen() {
  const { t } = useTranslation("studio");
  return (seconds: number) => {
    if (seconds < 60) return t("in.lessMinute");
    if (seconds < 3600) return t("in.minutes", { count: Math.round(seconds / 60) });
    if (seconds < 86_400) return t("in.hours", { count: Math.round(seconds / 3600) });
    return t("in.days", { count: Math.round(seconds / 86_400) });
  };
}
