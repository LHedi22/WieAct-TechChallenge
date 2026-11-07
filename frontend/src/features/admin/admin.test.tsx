import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminApp from "./AdminApp";
import type { Stats, Switches } from "./adminApi";

const switches = (over: Partial<Record<string, unknown>> = {}): Switches => ({
  switches: [
    {
      key: "force_quick_mode",
      value: null,
      effective: false,
      env_note: null,
      updated_at: null,
      updated_by: null,
    },
    {
      key: "offline_demo_mode",
      value: null,
      effective: "auto",
      env_note: "auto = environment (auto)",
      updated_at: null,
      updated_by: null,
    },
    {
      key: "pause_background_lane",
      value: null,
      effective: false,
      env_note: null,
      updated_at: null,
      updated_by: null,
    },
    {
      key: "llm_max_rpm_override",
      value: null,
      effective: 18,
      env_note: null,
      updated_at: null,
      updated_by: null,
    },
  ].map((s) => ({ ...s, ...(over[s.key] as object) })) as Switches["switches"],
  app_env: "development",
  configured_provider: "mock",
  provider: "mock",
  offline_now: false,
  llm_max_rpm: 18,
  force_quick_max_minutes: 60,
});

const stats: Stats = {
  provider: "cloud",
  calls: 40,
  ok: 38,
  cache_hits: 12,
  repeated_identical: 0,
  compact_share: 0.7,
  by_tier: { compact: { calls: 28, tokens_in: 1, tokens_out: 1, avg_latency_ms: 2000 } },
  by_task: { QUIZ_GENERATE: 4 },
  refusals: { saturated: 2 },
  fallbacks: 1,
  forced_fallbacks: 3,
  quota_headers_seen: [],
};

function serve({ signedIn = true, enabled = true } = {}) {
  let authed = signedIn;
  const calls: { path: string; method: string; headers: Record<string, string>; body?: unknown }[] =
    [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(url);
    const method = init?.method ?? "GET";
    const headers = (init?.headers ?? {}) as Record<string, string>;
    calls.push({
      path: u.pathname,
      method,
      headers,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    if (!enabled) return new Response('{"detail":"Not Found"}', { status: 404 });
    if (u.pathname === "/api/admin/session" && method === "POST") {
      authed = true;
      return new Response(JSON.stringify({ actor: "Hedi", via: "cookie", expires_at: null }));
    }
    if (!authed) return new Response('{"detail":"errors.admin_required"}', { status: 401 });
    if (u.pathname === "/api/admin/me")
      return new Response(JSON.stringify({ actor: "Hedi", via: "cookie", expires_at: null }));
    if (u.pathname === "/api/admin/switches") return new Response(JSON.stringify(switches()));
    if (u.pathname === "/api/admin/switches/force_quick_mode")
      return new Response(
        JSON.stringify(
          switches({
            force_quick_mode: {
              value: "2026-11-09T12:00:00Z",
              effective: true,
              updated_by: "Hedi",
              updated_at: "2026-11-09T11:50:00Z",
            },
          }),
        ),
      );
    if (u.pathname === "/api/admin/stats") return new Response(JSON.stringify(stats));
    return new Response('{"detail":"Not Found"}', { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function show(path = "/admin") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
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

describe("Admin", () => {
  it("says the admin side is off when the server has no token", async () => {
    serve({ enabled: false });
    show();
    expect(await screen.findByRole("heading", { name: "Admin is off" })).toBeInTheDocument();
  });

  it("signs in with the token and then forgets it", async () => {
    const calls = serve({ signedIn: false });
    show();
    const token = await screen.findByLabelText("Admin token");
    await userEvent.type(token, "secret-token");
    await userEvent.type(screen.getByLabelText(/Your name/), "Hedi");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Switches" })).toBeInTheDocument();
    const signIn = calls.find((c) => c.path === "/api/admin/session");
    expect(signIn?.body).toEqual({ token: "secret-token", label: "Hedi" });
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
  });

  it("turns Quick mode on with the CSRF header and shows who changed it", async () => {
    const calls = serve();
    show("/admin/switches");
    const card = (await screen.findByRole("heading", { name: "Force Quick mode" })).closest(
      "section",
    ) as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(within(card).getByText(/Changed by Hedi/)).toBeInTheDocument());
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.path).toBe("/api/admin/switches/force_quick_mode");
    expect(put?.headers["X-Admin-Action"]).toBe("1");
    expect(put?.body).toEqual({ value: 10, reason: null });
    expect(calls.filter((c) => c.method === "GET").every((c) => !c.headers["X-Admin-Action"])).toBe(
      true,
    );
  });

  it("shows forced Quick mode apart from real fallbacks", async () => {
    serve();
    show("/admin/stats");
    expect(await screen.findByText("Real fallbacks")).toBeInTheDocument();
    const real = screen.getByText("Real fallbacks").parentElement as HTMLElement;
    const forced = screen.getByText("Forced Quick mode").parentElement as HTMLElement;
    expect(within(real).getByText("1")).toBeInTheDocument();
    expect(within(forced).getByText("3")).toBeInTheDocument();
  });
});
