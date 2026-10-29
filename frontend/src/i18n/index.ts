import i18n, { type Resource } from "i18next";
import ICU from "i18next-icu";
import { initReactI18next } from "react-i18next";
import ar from "./ar.json";
import arTN from "./ar-TN.json";
import en from "./en.json";
import fr from "./fr.json";
import type { Language } from "./languages";

export const NAMESPACES = ["common", "styleguide", "dev", "worlds"] as const;

/** Locale files hold one object per namespace; `_review` (Darija review notes) is metadata. */
function toResource(file: Record<string, unknown>): Resource[string] {
  const namespaces = { ...file };
  delete namespaces._review;
  return namespaces as Resource[string];
}

export const resources: Record<Language, Resource[string]> = {
  en: toResource(en),
  fr: toResource(fr),
  ar: toResource(ar),
  "ar-TN": toResource(arTN),
};

export function initI18n(lng: Language = "en") {
  if (!i18n.isInitialized) {
    void i18n
      .use(ICU)
      .use(initReactI18next)
      .init({
        resources,
        lng,
        // Darija falls back to MSA Arabic, then English.
        fallbackLng: { "ar-TN": ["ar", "en"], default: ["en"] },
        ns: NAMESPACES,
        defaultNS: "common",
        interpolation: { escapeValue: false },
        returnNull: false,
      });
  }
  return i18n;
}

export default i18n;
