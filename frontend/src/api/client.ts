import type { components } from "./schema";

export type JobView = components["schemas"]["JobView"];
export type JobCreated = components["schemas"]["JobCreated"];
export type DemoJobIn = components["schemas"]["DemoJobIn"];
export type SystemStatus = components["schemas"]["SystemStatus"];

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

/** Errors carry an i18n key from the backend (`errors.*`), never raw server text. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public key: string,
  ) {
    super(key);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(0, "errors.network");
  }
  if (!res.ok) {
    let key = "errors.unexpected";
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail.startsWith("errors.")) key = body.detail;
    } catch {
      /* keep the generic key */
    }
    throw new ApiError(res.status, key);
  }
  return (await res.json()) as T;
}

export const api = {
  job: (id: string) => request<JobView>(`/api/jobs/${id}`),
  cancelJob: (id: string) => request<JobView>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  startDemoJob: (body: Partial<DemoJobIn>) =>
    request<JobCreated>("/api/dev/demo-jobs", { method: "POST", body: JSON.stringify(body) }),
  systemStatus: () => request<SystemStatus>("/api/system/status"),
};
