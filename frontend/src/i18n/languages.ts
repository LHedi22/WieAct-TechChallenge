export const LANGUAGES = ["en", "fr", "ar", "ar-TN"] as const;
export type Language = (typeof LANGUAGES)[number];

export const RTL_LANGUAGES: ReadonlySet<Language> = new Set(["ar", "ar-TN"]);

export function dirFor(lang: Language): "ltr" | "rtl" {
  return RTL_LANGUAGES.has(lang) ? "rtl" : "ltr";
}

export function isLanguage(value: unknown): value is Language {
  return typeof value === "string" && (LANGUAGES as readonly string[]).includes(value);
}

/** Western digits everywhere (DESIGN.md §RTL), even in Arabic. */
export function numberLocale(lang: string): string {
  return `${lang}-u-nu-latn`;
}
