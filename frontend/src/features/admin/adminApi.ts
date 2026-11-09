// Admin API client (English only, no i18n: DECISIONS.md 2026-11-08). The admin cookie is
// HttpOnly; the token is sent once to /api/admin/session and never stored in the browser.
import type { components } from "@/api/schema";

type S = components["schemas"];
export type AdminMe = S["AdminMe"];
export type Switches = S["Switches"];
export type Switch = S["Switch"];
export type SwitchKey = S["Switch"]["key"];
export type Stats = S["Stats"];

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class AdminError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const KNOWN: Record<string, string> = {
  "errors.admin_required": "Please sign in (the admin session ended or the token is wrong).",
  "errors.too_many_attempts": "Too many sign-in attempts. Wait a minute and try again.",
  "errors.admin_action_header": "The request was refused (missing X-Admin-Action header).",
};

function describe(status: number, detail: unknown): string {
  if (status === 404) return "The admin side is off on this server (ADMIN_TOKEN is blank).";
  if (typeof detail === "string") return KNOWN[detail] ?? detail;
  if (Array.isArray(detail))
    return detail
      .map((d: { msg?: string; loc?: unknown[] }) =>
        [d.loc?.slice(1).join("."), d.msg].filter(Boolean).join(": "),
      )
      .join("; ");
  return `Request failed (${status}).`;
}

export async function adminCall<T>(
  path: string,
  init: { method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; body?: unknown } = {},
): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = {};
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  // CSRF defence: every mutating admin route needs this custom header.
  if (method !== "GET") headers["X-Admin-Action"] = "1";
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      credentials: "include",
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new AdminError(0, "The API can't be reached.");
  }
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail;
    } catch {
      /* no body */
    }
    throw new AdminError(res.status, describe(res.status, detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const adminApi = {
  me: () => adminCall<AdminMe>("/api/admin/me"),
  signIn: (token: string, label: string) =>
    adminCall<AdminMe>("/api/admin/session", { method: "POST", body: { token, label } }),
  signOut: () => adminCall<void>("/api/admin/session", { method: "DELETE" }),
  switches: () => adminCall<Switches>("/api/admin/switches"),
  setSwitch: (key: SwitchKey, value: unknown, reason?: string) =>
    adminCall<Switches>(`/api/admin/switches/${key}`, {
      method: "PUT",
      body: { value, reason: reason || null },
    }),
  stats: (provider: string) =>
    adminCall<Stats>(`/api/admin/stats?provider=${encodeURIComponent(provider)}`),
};
