import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { numberLocale } from "@/i18n/languages";

/** Locale-aware grouping with Western digits in every language. */
export function useNumberFormat() {
  const { i18n } = useTranslation();
  return useMemo(() => new Intl.NumberFormat(numberLocale(i18n.language)), [i18n.language]);
}
