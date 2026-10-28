import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { JobView } from "@/api/client";
import { stagesOf } from "@/hooks/useJob";
import i18n from "@/i18n";
import { JobProgress } from "./JobProgress";

const base: JobView = {
  id: "00000000-0000-0000-0000-000000000001",
  kind: "DEMO_SUMMARY",
  lane: "interactive",
  status: "queued",
  stage: null,
  stages: ["reading_chapter", "writing_summary"],
  queue_position: null,
  eta_s: null,
  waiting_reason: null,
  quick_mode: false,
  cost: 0,
  result: null,
  error: null,
  created_at: "2026-10-28T12:00:00Z",
  finished_at: null,
};

function respond(routes: Record<string, JobView>) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${new URL(url).pathname}`;
    const body = routes[key];
    return new Response(JSON.stringify(body ?? { detail: "errors.job_not_found" }), {
      status: body ? 200 : 404,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function show(lang: "en" | "ar" = "en") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n.cloneInstance({ lng: lang })}>
      <QueryClientProvider client={qc}>
        <JobProgress jobId={base.id}>
          {(result) => <p>summary: {String((result as { text: string }).text)}</p>}
        </JobProgress>
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

const GET = `GET /api/jobs/${base.id}`;
const CANCEL = `POST /api/jobs/${base.id}/cancel`;

afterEach(() => vi.unstubAllGlobals());

describe("stagesOf", () => {
  it("maps the backend stage to done / in progress / next", () => {
    expect(stagesOf({ ...base, status: "running", stage: "writing_summary" })).toEqual([
      { key: "reading_chapter", state: "done" },
      { key: "writing_summary", state: "inProgress" },
    ]);
    expect(stagesOf(base).map((s) => s.state)).toEqual(["next", "next"]);
    expect(
      stagesOf({ ...base, status: "done", stage: "reading_chapter" }).map((s) => s.state),
    ).toEqual(["done", "done"]);
  });
});

describe("JobProgress", () => {
  it("shows queue position, ETA, why it waits, and the cancel button", async () => {
    respond({ [GET]: { ...base, queue_position: 3, eta_s: 20, waiting_reason: "quota" } });
    show();
    expect(await screen.findByText(/number 3 in line \(about 20 s\)/)).toBeInTheDocument();
    expect(screen.getByText(/asked us to wait/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel and keep my coins" })).toBeEnabled();
    expect(screen.getByText("Reading the chapter")).toBeInTheDocument();
  });

  it("renders the result with the Quick mode chip", async () => {
    respond({ [GET]: { ...base, status: "done", quick_mode: true, result: { text: "ok" } } });
    show();
    expect(await screen.findByText("summary: ok")).toBeInTheDocument();
    expect(screen.getByText("Quick mode")).toBeInTheDocument();
  });

  it("shows the translated error key on failure, never raw text", async () => {
    respond({ [GET]: { ...base, status: "failed", error: "errors.ai_failed" } });
    show("ar");
    expect(await screen.findByText(/أُعيدت إليك عملاتك/)).toBeInTheDocument();
  });

  it("cancels while queued and keeps the coins", async () => {
    const fetchMock = respond({
      [GET]: { ...base, queue_position: 1, eta_s: 5 },
      [CANCEL]: { ...base, status: "cancelled" },
    });
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Cancel and keep my coins" }));
    await waitFor(() => expect(screen.getByText(/Your coins were kept/)).toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true);
  });

  it("shows a network error when the API is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("down"))),
    );
    show();
    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument();
  });
});
