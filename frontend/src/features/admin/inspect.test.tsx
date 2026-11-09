import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminApp from "./AdminApp";

const student = {
  user: { id: "u1", nickname: "ana_admin", ui_language: "ar", created_at: "2026-11-01T10:00:00Z" },
  wallet: {
    free: 17,
    earned: 7,
    purchased: 0,
    coins: 24,
    today: "2026-11-09",
    earned_today: 3,
    daily_earn_cap: 10,
    pass_until: null,
    pass_active: false,
    pass_used_today: 0,
    pass_daily_limit: 15,
    has_daily_row_today: true,
    spending_order: ["free", "earned", "purchased"],
    days: [
      {
        day: "2026-11-09",
        net: 17,
        earned: 0,
        rows: [
          {
            created_at: "2026-11-09T08:00:00Z",
            bucket: "free",
            kind: "daily",
            delta: 20,
            ref: null,
          },
        ],
      },
    ],
  },
  points: { total: 30, streak: 2, rows: [], ranks: [] },
  learning: {
    levels: [],
    mastery: [{ chapter_id: "c1", chapter: "Limits", course_id: "k1", mastery: 40, weak: true }],
  },
  daily: null,
  activity: {
    quiz_attempts: [],
    tutor_sessions: [],
    peer_questions: [],
    peer_answers: [],
    flashcard_reviews: [],
    jobs: [],
  },
  invariants: [
    { check: "negative_bucket", ok: true, description: "no bucket below zero", rows: [] },
    {
      check: "earned_cap",
      ok: false,
      description: "earned coins per day ≤ DAILY_EARN_CAP (10)",
      rows: [{ day: "2026-11-08", earned: 12 }],
    },
  ],
};

const price = {
  activity: "quiz",
  base_cost: 5,
  cached: false,
  exam_pass: false,
  pool: null,
  split: { free: 5 },
  pays: 5,
  affordable: true,
  steps: [
    "No unseen set for intermediate/ar: a new set costs 5.",
    "Paid in spending order: 5 free.",
  ],
};

function serve() {
  const seen: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const u = new URL(url);
      seen.push(`${u.pathname}${u.search}`);
      if (u.pathname === "/api/admin/me")
        return new Response(JSON.stringify({ actor: "Hedi", via: "cookie", expires_at: null }));
      if (u.pathname === "/api/admin/debug/students/u1")
        return new Response(JSON.stringify(student));
      if (u.pathname === "/api/admin/debug/students/u1/price")
        return new Response(JSON.stringify(price));
      return new Response('{"detail":"Not Found"}', { status: 404 });
    }),
  );
  return seen;
}

afterEach(() => vi.unstubAllGlobals());

describe("Student inspector", () => {
  it("shows failing invariants with their rows and explains a price", async () => {
    const seen = serve();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/admin/debug/students/u1"]}>
          <Routes>
            <Route path="/admin/*" element={<AdminApp />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { name: "ana_admin" })).toBeInTheDocument();
    expect(screen.getByText("1 failing")).toBeInTheDocument();
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText(/"earned": 12/)).toBeInTheDocument();
    expect(screen.getByText("24 = free 17 + earned 7 + purchased 0")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Explain" }));
    expect(await screen.findByText("Paid in spending order: 5 free.")).toBeInTheDocument();
    expect(seen).toContain(
      "/api/admin/debug/students/u1/price?activity=quiz&level=intermediate&chapter_id=c1",
    );
  });
});
