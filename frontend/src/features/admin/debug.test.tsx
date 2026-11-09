import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminApp from "./AdminApp";

const call = {
  id: 7,
  ts: "2026-11-09T01:00:00Z",
  task_kind: "NOTES_WRITE",
  lane: "interactive",
  tier: "mid",
  provider: "mock",
  model: "mock-mid",
  pattern: "plan-once",
  status_code: 503,
  tokens_in: 0,
  tokens_out: 0,
  latency_ms: 20,
  cache_hit: false,
  single_flight: false,
  fallback: false,
  forced: false,
  refusal_reason: "saturated",
  request_hash: "abc",
  job_id: "j1",
  attempt: 1,
  debug: false,
  outcome: "503",
};

const live = {
  now: "2026-11-09T01:00:05Z",
  workers: [
    {
      worker_id: "host:1:abc",
      updated_at: "2026-11-09T01:00:04Z",
      age_s: 1.2,
      fresh: true,
      in_flight: { interactive: 1, background: 0 },
      lane_limits: { interactive: 6, background: 2 },
      job_ids: ["j1"],
      last_error: null,
      provider: "mock",
      offline: false,
      slot_live: false,
      quota: { remaining: null, reset_s: null, low: false, background_pause_s: 0 },
      limiter: {
        active: 1,
        concurrency: 2,
        max_active: 2,
        waiting: { interactive: 0, background: 0 },
        buckets: {
          chat: { tokens: 1.5, capacity: 3, rpm: 18 },
          embed: { tokens: 3, capacity: 3, rpm: 18 },
        },
        rpm_last_60s: { chat: 4, embed: 0 },
      },
    },
  ],
  queue: [
    { lane: "interactive", ready: 2, waiting: 0, running: 1, next_not_before: null },
    { lane: "background", ready: 0, waiting: 1, running: 0, next_not_before: null },
  ],
  calls_per_minute: [{ minute: "2026-11-09T01:00:00Z", tier: "mid", calls: 3 }],
  flags: { trace_prompts_until: "2026-11-09T02:00:00Z" },
  trace_on: true,
  app_env: "production",
  last_calls: [call],
};

const detail = {
  call,
  trace: {
    created_at: "2026-11-09T01:00:00Z",
    messages: [{ role: "user", content: "Limits" }],
    reply: null,
    reply_without_think: null,
    parsed: null,
    error: "saturated (503): busy",
  },
  repair: null,
  replay: {
    available: false,
    targets: [],
    reason: "Production runs on the platform only.",
  },
  tracing_note: null,
};

function serve() {
  const seen: { path: string; method: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(url);
      seen.push({ path: u.pathname, method: init?.method ?? "GET" });
      if (u.pathname === "/api/admin/me")
        return new Response(JSON.stringify({ actor: "Hedi", via: "cookie", expires_at: null }));
      if (u.pathname === "/api/admin/debug/live") return new Response(JSON.stringify(live));
      if (u.pathname === "/api/admin/debug/calls/7") return new Response(JSON.stringify(detail));
      if (u.pathname === "/api/admin/switches/trace_prompts") return new Response("{}");
      return new Response('{"detail":"Not Found"}', { status: 404 });
    }),
  );
  return seen;
}

function open(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/admin/*" element={<AdminApp />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Admin debug", () => {
  it("shows the worker heartbeat, the call strip and a production trace warning", async () => {
    const seen = serve();
    open("/admin/debug/live");
    expect(await screen.findByText("host:1:abc")).toBeInTheDocument();
    expect(screen.getByText(/1\/2 \(max seen 2\)/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /#7 NOTES_WRITE · mid · 503 saturated/ }),
    ).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("turn it off before a user test");
    await userEvent.click(screen.getByRole("button", { name: "Turn off now" }));
    expect(seen).toContainEqual({ path: "/api/admin/switches/trace_prompts", method: "PUT" });
  });

  it("says why replay is unavailable instead of hiding it", async () => {
    serve();
    open("/admin/debug/calls/7");
    expect(await screen.findByText("Messages sent")).toBeInTheDocument();
    expect(screen.getByText("saturated (503): busy")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Replay is unavailable here. Production runs on the platform only.",
    );
    expect(screen.queryByRole("button", { name: "Replay" })).toBeNull();
  });
});
