import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ArenaDetail, ArenaFeed, Economy, Leaderboard, Wallet } from "@/api/client";
import { useUiStore } from "@/app/uiStore";
import i18n from "@/i18n";
import type { Language } from "@/i18n/languages";
import { LeaderboardCard } from "@/features/leaderboard/Leaderboard";
import { OutOfCoinsDialog } from "@/features/wallet/OutOfCoinsDialog";
import { ArenaPage } from "./ArenaPage";
import { ScoreCard } from "./ScoreCard";

type Handler = (body: unknown) => [number, unknown];

function serve(routes: Record<string, unknown>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(url);
      const key = `${init?.method ?? "GET"} ${u.pathname}`;
      calls.push(key);
      const h = routes[key];
      if (typeof h === "function") {
        const [status, out] = (h as Handler)(init?.body ? JSON.parse(String(init.body)) : null);
        return new Response(status === 204 ? null : JSON.stringify(out), { status });
      }
      if (h === undefined) return new Response('{"detail":"errors.unexpected"}', { status: 404 });
      return new Response(JSON.stringify(h), { status: 200 });
    }),
  );
  return calls;
}

function show(ui: ReactElement, path = "/", route = "/", lang: Language = "en") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n.cloneInstance({ lng: lang })}>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={path} element={ui} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  useUiStore.getState().setOutOfCoins(false);
});

const economy: Economy = {
  daily_free_coins: 20,
  daily_earn_cap: 10,
  exam_pass_daily_limit: 15,
  cost: { quiz: 5, tutor_session: 8, peer_question: 2, teachback_solo: 8 },
  earn: { peer_answer_good: 3 },
  points: {},
  peer_answer_threshold: 70,
  products: { coin_pack: { coins: 50, price_tnd: 2 }, exam_pass: { days: 14, price_tnd: 10 } },
  cosmetics: {},
  buildings: {},
};
const wallet: Wallet = {
  coins: 0,
  free_today: 0,
  earned: 0,
  purchased: 0,
  earned_today: 0,
  points: 120,
  streak: 2,
  refill_at: new Date(Date.now() + 3 * 3600_000 + 5 * 60_000).toISOString(),
  exam_pass_until: null,
  exam_pass_left_today: null,
};

describe("Out of coins", () => {
  it("shows refill, +3 per good answer, an honest Exam Pass and a labelled demo purchase", async () => {
    const calls = serve({
      "GET /api/economy": economy,
      "GET /api/wallet": wallet,
      "POST /api/wallet/demo-purchase": { demo: true, wallet: { ...wallet, coins: 50 } },
    });
    useUiStore.getState().setOutOfCoins(true);
    show(<OutOfCoinsDialog />);
    expect(await screen.findByText("You're out of coins for today")).toBeInTheDocument();
    expect(screen.getByText("3h 5m")).toBeInTheDocument();
    expect(screen.getByText("+3 each")).toBeInTheDocument(); // DESIGN.md fix 5, not +5
    expect(screen.getByText(/14 days · up to 15 AI activities a day/)).toBeInTheDocument();
    expect(screen.queryByText(/unlimited/i)).toBeNull(); // DESIGN.md fix 6
    expect(screen.getByText(/50 coins, about 10 quizzes/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Demo purchase · 2 TND" }));
    expect(await screen.findByText(/You now have 50 coins/)).toBeInTheDocument();
    expect(calls).toContain("POST /api/wallet/demo-purchase");
    await userEvent.keyboard("{Escape}");
    expect(useUiStore.getState().outOfCoins).toBe(false);
  });
});

describe("Score card", () => {
  it("underlines each quoted mistake and lists what to fix", () => {
    show(
      <ScoreCard
        score={74}
        confidence="medium"
        text="Undo removes the first action you did, like a queue at the bank."
        errors={[
          { quote: "the first action you did", fix: "Undo removes the most recent action." },
          { quote: "a queue at the bank", fix: "A queue is first-in, first-out." },
        ]}
        good="You linked the order of actions to undo."
        missing={["LIFO"]}
      />,
    );
    const marks = document.querySelectorAll("mark");
    expect([...marks].map((m) => m.textContent)).toEqual([
      "the first action you did",
      "a queue at the bank",
    ]);
    expect(screen.getByText("2 things to fix")).toBeInTheDocument();
    expect(screen.getByText("Good: You linked the order of actions to undo.")).toBeInTheDocument();
    expect(screen.getByText("Confidence: medium")).toBeInTheDocument();
  });
});

describe("Leaderboard card", () => {
  const board: Leaderboard = {
    scope: "world",
    period: "week",
    since: null,
    opted_in: true,
    entries: [
      { rank: 1, nickname: null, avatar: null, points: 80, is_me: false },
      { rank: 2, nickname: "SeaTurtle42", avatar: null, points: 50, is_me: true },
    ],
    me: { rank: 2, nickname: "SeaTurtle42", avatar: null, points: 50, is_me: true },
  };

  it("keeps a hidden classmate's rank without their nickname, in Arabic too", async () => {
    serve({ "GET /api/leaderboard": board });
    show(<LeaderboardCard worldId="w1" />, "/", "/", "ar");
    expect(await screen.findByText("مستكشف مخفي")).toBeInTheDocument();
    expect(screen.getByText("SeaTurtle42")).toBeInTheDocument();
  });
});

describe("Teach-Back peer room", () => {
  const feed: ArenaFeed = {
    chapter_id: "ch1",
    chapter_title: "Stacks & queues",
    course_name: "Data Structures",
    ask_cost: 2,
    solo_cost: 8,
    questions: [
      {
        id: "q1",
        text: "Why does a stack make undo easy?",
        author: { nickname: "MintTea99", avatar: null },
        is_mine: true,
        status: "open",
        reject_reason: null,
        answers: 1,
        pinned: false,
        answered_by_me: false,
        created_at: "2026-11-04T09:00:00Z",
      },
    ],
  };
  const detail: ArenaDetail = {
    question: feed.questions[0]!,
    answers: [
      {
        id: "a1",
        author: { nickname: "OliveOwl", avatar: null },
        is_mine: false,
        text: "Undo pops the most recent action off the stack.",
        status: "graded",
        score: 92,
        confidence: "high",
        helpful: 6,
        voted: false,
        pinned: false,
        feedback: null,
        reject_flag: null,
        grading_job_id: null,
        updated_at: "2026-11-04T09:05:00Z",
      },
    ],
    my_answer: null,
    can_answer: false,
    can_pin: true,
    threshold: 70,
  };

  it("lets the asker see a classmate's score and pin it as the best answer", async () => {
    const calls = serve({
      "GET /api/economy": economy,
      "GET /api/arena/questions": feed,
      "GET /api/arena/questions/q1": detail,
      "POST /api/arena/answers/a1/pin": () => [204, null],
    });
    show(<ArenaPage />, "/w/:worldId/c/:courseId/arena", "/w/w1/c/c1/arena?chapter=ch1");
    expect(
      await screen.findByRole("heading", { name: feed.questions[0]!.text }),
    ).toBeInTheDocument();
    expect(screen.getByText("92")).toBeInTheDocument();
    expect(screen.getByText("Marked helpful by 6 classmates")).toBeInTheDocument();
    expect(screen.getByText("+3 coins for each good answer (score 70+)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Pin as best answer" }));
    await waitFor(() => expect(calls).toContain("POST /api/arena/answers/a1/pin"));
  });
  it("shows my unsure answer as waiting for a check, with feedback and no score", async () => {
    const mine: ArenaDetail["answers"][number] = {
      ...detail.answers[0]!,
      id: "a2",
      is_mine: true,
      status: "pending_review",
      score: null,
      confidence: "low",
      feedback: {
        errors: [],
        good: "You linked undo to the order.",
        missing: ["LIFO"],
        quick_mode: false,
      },
    };
    serve({
      "GET /api/economy": economy,
      "GET /api/arena/questions": feed,
      "GET /api/arena/questions/q1": { ...detail, answers: [], my_answer: mine, can_pin: false },
    });
    show(<ArenaPage />, "/w/:worldId/c/:courseId/arena", "/w/w1/c/c1/arena?chapter=ch1", "ar");
    expect(await screen.findByText("في انتظار التحقق")).toBeInTheDocument();
    expect(screen.queryByText("92")).not.toBeInTheDocument();
    expect(screen.getByText(/You linked undo/)).toBeInTheDocument();
  });
});
