import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { dirFor } from "@/i18n/languages";
import { useUiStore } from "./uiStore";

/** Keeps i18next, <html lang> and <html dir> in sync with the chosen language. */
export function useDocumentLanguage() {
  const language = useUiStore((s) => s.language);
  const reducedMotion = useUiStore((s) => s.reducedMotion);
  const { i18n } = useTranslation();

  useEffect(() => {
    if (i18n.language !== language) void i18n.changeLanguage(language);
    const html = document.documentElement;
    html.lang = language;
    html.dir = dirFor(language);
  }, [language, i18n]);

  useEffect(() => {
    document.documentElement.dataset.reducedMotion = String(reducedMotion);
  }, [reducedMotion]);
}
