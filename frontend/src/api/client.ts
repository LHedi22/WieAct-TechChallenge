import { useUiStore } from "@/app/uiStore";
import type { components } from "./schema";

type S = components["schemas"];
export type JobView = S["JobView"];
export type JobCreated = S["JobCreated"];
export type DemoJobIn = S["DemoJobIn"];
export type SystemStatus = S["SystemStatus"];
export type WorldOut = S["WorldOut"];
export type WorldSummary = S["WorldSummary"];
export type CourseOut = S["CourseOut"];
export type ChapterOut = S["ChapterOut"];
export type DocumentOut = S["DocumentOut"];
export type UploadOut = S["UploadOut"];
export type IndexingOut = S["IndexingOut"];
export type IndexingChapter = S["IndexingChapter"];

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

/** Until sign-in exists (M3) the dev backend identifies the user by nickname (X-Dev-User). */
function identity(): Record<string, string> {
  const { devUser, language } = useUiStore.getState();
  return { "X-Dev-User": devUser, "X-UI-Language": language };
}

async function request<T>(path: string, init?: RequestInit, json = true): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      credentials: "include",
      ...init,
      headers: {
        ...(json ? { "Content-Type": "application/json" } : {}),
        ...identity(),
        ...init?.headers,
      },
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
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  job: (id: string) => request<JobView>(`/api/jobs/${id}`),
  cancelJob: (id: string) => request<JobView>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  startDemoJob: (body: Partial<DemoJobIn>) => post<JobCreated>("/api/dev/demo-jobs", body),
  systemStatus: () => request<SystemStatus>("/api/system/status"),

  myWorlds: () => request<WorldSummary[]>("/api/worlds"),
  createWorld: (name: string) => post<WorldOut>("/api/worlds", { name }),
  joinWorld: (code: string) => post<WorldOut>("/api/worlds/join", { code }),
  world: (id: string) => request<WorldOut>(`/api/worlds/${id}`),
  addCourse: (worldId: string, name: string, chapters: string[]) =>
    post<CourseOut>(`/api/worlds/${worldId}/courses`, { name, chapters }),
  deleteCourse: (courseId: string) =>
    request<void>(`/api/courses/${courseId}`, { method: "DELETE" }),
  addChapter: (courseId: string, title: string) =>
    post<ChapterOut>(`/api/courses/${courseId}/chapters`, { title }),
  upload: (chapterId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadOut>(
      `/api/chapters/${chapterId}/documents`,
      { method: "POST", body: form },
      false, // the browser sets the multipart boundary
    );
  },
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),
  indexing: (worldId: string) => request<IndexingOut>(`/api/worlds/${worldId}/indexing`),
};
