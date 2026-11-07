// Shared admin helpers (kept out of component files for fast refresh).
export const inputClass =
  "min-h-11 w-full rounded-soft border-2 border-ink/60 bg-white px-2 py-1.5 text-body text-ink focus:border-sea-ink focus:outline focus:outline-2 focus:outline-sea";

export function when(iso: string | null | undefined): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" });
}
