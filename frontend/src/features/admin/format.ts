// Shared admin helpers (kept out of component files for fast refresh).
import en from "@/i18n/en.json";

const ERRORS = (en as { common: { errors: Record<string, string> } }).common.errors;

/** An `errors.*` key stored on a job or document, as the English sentence students see. */
export function plainError(key: string | null | undefined): string {
  if (!key) return "—";
  const [ns, name] = key.split(".", 2);
  const text = ns === "errors" && name ? ERRORS[name] : undefined;
  return text ? text.replace(/\{[^}]*\}/g, "…") : key;
}

export const inputClass =
  "min-h-11 w-full rounded-soft border-2 border-ink/60 bg-white px-2 py-1.5 text-body text-ink focus:border-sea-ink focus:outline focus:outline-2 focus:outline-sea";

/** Local time as 2026-11-08 00:52 (unambiguous on screen and in the video). */
export function when(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
