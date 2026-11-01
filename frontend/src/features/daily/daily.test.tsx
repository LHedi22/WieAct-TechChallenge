import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Daily, DailyChallenge, Economy } from "@/api/client";
import i18n from "@/i18n";
import type { Language } from "@/i18n/languages";
import { ChallengesCard } from "./Challenges";
import { DailyReturnPage } from "./DailyReturnPage";

function serve(routes: Record<string, unknown>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${new URL(url).pathname}`;
      calls.push(key);
      const body = routes[key];
      if (body === undefined)
        return new Response('{"detail":"errors.unexpected"}', { status: 404 });
      return new Response(JSON.stringify(body), { status: 200 });
    }),
  );
  return calls;
}

function show(ui: ReactElement, path: string, route: string, lang: Language = "en") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n.cloneInstance({ lng: lang })}>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={path} element={ui} />
            <Route path="/worlds/:worldId" element={<p>the map</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

const economy = {
  daily_free_coins: 20,
  earn: { daily_challenge: 3 },
  points: { daily_challenge: 15, all_challenges_bonus: 30 },
} as unknown as Economy;

const ch = (over: Partial<DailyChallenge>): DailyChallenge => ({
  type: "quiz_questions",
  target: 10,
  progress: 0,
  done: false,
  why: null,
  world_id: "w1",
  course_id: "c1",
  chapter_id: "ch1",
  course: "Calculus I",
  chapter: "Limits",
  ...over,
});

const daily: Daily = {
  date: "2026-11-02",
  challenges: [
    ch({ progress: 7 }),
    ch({ type: "quiz_score", target: 70, why: "Limits is your weakest chapter." }),
    ch({ type: "teachback", target: 1, progress: 1, done: true }),
  ],
  all_done: false,
  planned_by: "ai",
  plan_job_id: null,
  message: "One step at a time today.",
  first_open_today: true,
  returning: true,
  reminder_due: true,
  coins: 20,
  free_today: 20,
  streak: 4,
  refill_at: "2026-11-02T23:00:00Z",
};

afterEach(() => vi.unstubAllGlobals());

describe("Daily challenges", () => {
  it("shows 3 challenges with progress, rewards from the economy and the reminder", async () => {
    serve({ "GET /api/daily": daily, "GET /api/economy": economy });
    show(<ChallengesCard />, "/worlds/:worldId", "/worlds/w1");
    expect(await screen.findByText("Answer 10 quiz questions")).toBeInTheDocument();
    expect(screen.getByText("Score 70% on the Limits quiz")).toBeInTheDocument();
    expect(screen.getByText("Limits is your weakest chapter.")).toBeInTheDocument();
    expect(await screen.findAllByText("+3 coins · +15 pts")).toHaveLength(3);
    expect(screen.getByRole("progressbar", { name: "Answer 10 quiz questions" })).toHaveAttribute(
      "aria-valuenow",
      "7",
    );
    expect(screen.getByText(/today's challenges are waiting/)).toBeInTheDocument();
    expect(screen.getByText("Planned for you")).toBeInTheDocument();
    const link = screen.getAllByRole("link", { name: "Go" })[0];
    expect(link).toHaveAttribute("href", "/worlds/w1/courses/c1");
  });

  it("daily return screen: refilled coins, streak, challenges, then on to the map (AR)", async () => {
    const calls = serve({
      "GET /api/daily": daily,
      "GET /api/economy": economy,
      "POST /api/daily/seen": { ...daily, first_open_today: false },
    });
    show(<DailyReturnPage />, "/worlds/:worldId/today", "/worlds/w1/today", "ar");
    expect(await screen.findByText("مرحبًا بعودتك!")).toBeInTheDocument();
    expect(await screen.findByText(/عادت 20 عملة مجانية/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "إلى الخريطة" }));
    expect(await screen.findByText("the map")).toBeInTheDocument();
    expect(calls).toContain("POST /api/daily/seen");
  });
});
