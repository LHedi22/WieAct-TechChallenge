import i18n, { type BackendModule, type Resource } from "i18next";
import ICU from "i18next-icu";
import { initReactI18next } from "react-i18next";
import en from "./en.json";
import type { Language } from "./languages";

export const NAMESPACES = [
  "common",
  "styleguide",
  "dev",
  "worlds",
  "landing",
  "auth",
  "onboarding",
  "map",
  "island",
  "placement",
  "quiz",
  "tutor",
] as const;

/** Locale files hold one object per namespace; `_review` (Darija review notes) is metadata. */
function toResource(file: Record<string, unknown>): Resource[string] {
  const namespaces = { ...file };
  delete namespaces._review;
  return namespaces as Resource[string];
}

// English (every fallback ends there) is bundled; the other locales are their own chunks, loaded
// when chosen (audit OPT-21). Darija also loads Arabic, its first fallback.
const loaders = import.meta.glob<Record<string, unknown>>(
  ["./fr.json", "./ar.json", "./ar-TN.json"],
  { import: "default" },
);

const lazyLocales: BackendModule = {
  type: "backend",
  init() {},
  read(language, namespace, callback) {
    const load = loaders[`./${language}.json`];
    if (!load) return callback(null, {}); // en: already bundled
    load().then(
      (file) => callback(null, toResource(file)[namespace] ?? {}),
      (e: Error) => callback(e, null),
    );
  },
};

let ready: Promise<unknown> = Promise.resolve();

/** `preload`: locales to fetch now (tests load all of them once, then render synchronously). */
export function initI18n(lng: Language = "en", preload: Language[] = []) {
  if (!i18n.isInitialized) {
    ready = i18n
      .use(lazyLocales)
      .use(ICU)
      .use(initReactI18next)
      .init({
        resources: { en: toResource(en) },
        partialBundledLanguages: true,
        preload: [lng, ...preload],
        lng,
        // Darija falls back to MSA Arabic, then English.
        fallbackLng: { "ar-TN": ["ar", "en"], default: ["en"] },
        ns: NAMESPACES,
        defaultNS: "common",
        interpolation: { escapeValue: false },
        returnNull: false,
        // changeLanguage loads first, then switches: no Suspense boundary needed around the app
        react: { useSuspense: false },
      });
  }
  return i18n;
}

/** Resolves when the first language (and any preload) is in. */
export const i18nReady = () => ready;

export default i18n;
