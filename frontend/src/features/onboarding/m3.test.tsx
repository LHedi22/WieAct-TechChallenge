import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Economy, IslandOut, MapOut, Me, Wallet } from "@/api/client";
import i18n from "@/i18n";
import type { Language } from "@/i18n/languages";
import { AuthPage } from "@/features/auth/AuthPage";
import { IslandPage } from "@/features/island/IslandPage";
import { MapPage } from "@/features/map/MapPage";
import { PlacementPage } from "@/features/placement/PlacementPage";
import { OnboardingPage } from "./OnboardingPage";

const W = "11111111-1111-1111-1111-111111111111";
const C = "22222222-2222-2222-2222-222222222222";

const me: Me = {
  id: "u1",
  nickname: "SeaTurtle42",
  ui_language: "en",
  onboarded: true,
  avatar: { skin: "s2", outfit: "o1", extra: "cap" },
  has_worlds: true,
};
const economy: Economy = {
  daily_free_coins: 20,
  daily_earn_cap: 10,
  exam_pass_daily_limit: 15,
  cost: { quiz: 5, tutor_session: 8, placement_quiz: 0 },
  earn: {},
  points: {},
  peer_answer_threshold: 70,
  products: { coin_pack: { coins: 50, price_tnd: 2 }, exam_pass: { days: 14, price_tnd: 10 } },
  cosmetics: { cap: 0, glasses: 0, scarf: 0, chechia: 300, headphones: 500 },
  buildings: {},
};
const wallet: Wallet = {
  coins: 20,
  free_today: 20,
  earned: 0,
  purchased: 0,
  points: 0,
  streak: 0,
  earned_today: 0,
  refill_at: "2026-10-30T23:00:00Z",
  exam_pass_until: null,
  exam_pass_left_today: null,
};
const map: MapOut = {
  world_id: W,
  name: "Engineering 2B",
  join_code: "OLIVE-7Q2",
  creator: "BlueDoor7",
  is_creator: false,
  members: [
    { nickname: "BlueDoor7", avatar: null, is_me: false },
    { nickname: "SeaTurtle42", avatar: null, is_me: true },
  ],
  courses: [
    {
      id: C,
      name: "Calculus I",
      color_key: "island-1",
      ready: true,
      chapters: 3,
      level: null,
      mastery: 0,
    },
    {
      id: "c2",
      name: "Data Structures",
      color_key: "island-2",
      ready: true,
      chapters: 2,
      level: "advanced",
      mastery: 78,
    },
  ],
};
const island: IslandOut = {
  id: C,
  world_id: W,
  name: "Calculus I",
  color_key: "island-1",
  level: null,
  mastery: 0,
  chapters: [
    { id: "ch1", idx: 1, title: "Limits", ready: true, mastery: 30, weak: true },
    { id: "ch2", idx: 2, title: "Derivatives", ready: true, mastery: null, weak: false },
  ],
  buildings: [
    { key: "quiz_hall", cost: 5, free_if_cached: false, answer_cost: null },
    { key: "socratic_tutor", cost: 8, free_if_cached: false, answer_cost: null },
    { key: "study_studio", cost: 15, free_if_cached: true, answer_cost: null },
    { key: "audio_studio", cost: 15, free_if_cached: true, answer_cost: null },
    { key: "teachback_arena", cost: 2, free_if_cached: false, answer_cost: 0 },
  ],
  visitors: [{ nickname: "OliveOwl", avatar: null, chapter: "Limits" }],
};

type Routes = Record<string, unknown | ((body: unknown) => [number, unknown])>;

function serve(routes: Routes) {
  const calls: { key: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${new URL(url).pathname}`;
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ key, body });
      const handler = routes[key];
      if (typeof handler === "function") {
        const [status, out] = (handler as (b: unknown) => [number, unknown])(body);
        return new Response(JSON.stringify(out), { status });
      }
      if (handler === undefined)
        return new Response(JSON.stringify({ detail: "errors.unexpected" }), { status: 404 });
      return new Response(handler === null ? "null" : JSON.stringify(handler), { status: 200 });
    }),
  );
  return calls;
}

const BASE: Routes = {
  "GET /api/auth/session": me,
  "GET /api/economy": economy,
  "GET /api/wallet": wallet,
  "GET /api/worlds": [{ id: W, name: "Engineering 2B", join_code: "OLIVE-7Q2" }],
};

function show(ui: ReactElement, path: string, route: string, lang: Language = "en") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n.cloneInstance({ lng: lang })}>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={path} element={ui} />
            <Route path="*" element={<p>elsewhere</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Sign up / sign in", () => {
  it("checks the password length locally and shows the server's message key", async () => {
    const calls = serve({
      ...BASE,
      "POST /api/auth/signup": () => [409, { detail: "errors.nickname_taken" }],
    });
    const user = userEvent.setup();
    show(<AuthPage mode="signup" />, "/signup", "/signup");
    expect(
      screen.getByText("Your class sees this name. No real names or photos."),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("Nickname"), "SeaTurtle42");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create my account" }));
    expect(screen.getByText("At least 8 characters.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === "POST /api/auth/signup")).toBe(false);
    await user.type(screen.getByLabelText("Password"), "-long-enough");
    await user.click(screen.getByRole("button", { name: "Create my account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That nickname is taken");
  });
});

describe("Onboarding", () => {
  it("scores the style test on the server and shows the mix, then locks priced extras", async () => {
    const calls = serve({
      ...BASE,
      "POST /api/onboarding/style": {
        mix: { visual: 38, practice: 38, listening: 12, teaching: 12 },
        top: ["visual", "practice"],
        suggested_buildings: ["study_studio", "quiz_hall"],
      },
    });
    const user = userEvent.setup();
    show(<OnboardingPage />, "/welcome", "/welcome");
    expect(screen.getByText("Step 1 of 5 · About you")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    for (const pick of [
      "See it as a diagram",
      "Making a mind map",
      "A quick quiz",
      "A similar solved example",
    ]) {
      await user.click(screen.getByRole("radio", { name: new RegExp(pick) }));
      await user.click(screen.getByRole("button", { name: "Continue" }));
    }
    expect(calls.find((c) => c.key === "POST /api/onboarding/style")?.body).toEqual({
      answers: ["visual", "visual", "practice", "practice"],
    });
    await user.click(await screen.findByRole("button", { name: "Continue" })); // goals (optional)
    expect(await screen.findByText("You learn best with visuals and practice")).toBeInTheDocument();
    expect(screen.getByText(/point you to Study Studio and Quiz Hall/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Chechia/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Chechia/ })).toHaveTextContent("300 pts");
    expect(screen.getByRole("button", { name: /Glasses/ })).toBeEnabled();
  });

  it("Skip for now finishes onboarding", async () => {
    const calls = serve({
      ...BASE,
      "PUT /api/profile": { onboarded: true },
      "GET /api/auth/me": me,
    });
    const user = userEvent.setup();
    show(<OnboardingPage />, "/welcome", "/welcome");
    await user.click(screen.getByRole("button", { name: "Skip for now" }));
    await waitFor(() => expect(screen.getByText("elsewhere")).toBeInTheDocument());
    expect(calls.find((c) => c.key === "PUT /api/profile")?.body).toEqual({ finish: true });
  });
});

describe("World map", () => {
  it("locks islands until placement and lists courses in list view", async () => {
    serve({ ...BASE, [`GET /api/worlds/${W}/map`]: map });
    const user = userEvent.setup();
    show(<MapPage />, "/worlds/:worldId", `/worlds/${W}`);
    expect(await screen.findByText("Waiting for your placement quiz")).toBeInTheDocument();
    expect(screen.getByText("78% mastery")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start 3-minute quiz" })).toBeInTheDocument();
    expect(screen.getByTestId("class-code")).toHaveTextContent("OLIVE-7Q2");
    expect(screen.getByText("(you)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "List view" }));
    const list = screen.getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(list.some((t) => t.includes("Calculus I") && t.includes("3 chapters"))).toBe(true);
  });

  it("shows the empty world when nothing has risen yet", async () => {
    const empty = { ...map, courses: map.courses.map((c) => ({ ...c, ready: false })) };
    serve({ ...BASE, [`GET /api/worlds/${W}/map`]: empty });
    show(<MapPage />, "/worlds/:worldId", `/worlds/${W}`);
    expect(await screen.findByText("This world is still all sea")).toBeInTheDocument();
    expect(
      screen.getByText(/BlueDoor7 created Engineering 2B and invited you/),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 classmate is waiting with you/)).toBeInTheDocument();
  });

  it("renders in Arabic", async () => {
    serve({ ...BASE, [`GET /api/worlds/${W}/map`]: map });
    show(<MapPage />, "/worlds/:worldId", `/worlds/${W}`, "ar");
    expect(await screen.findByText("صفّك")).toBeInTheDocument();
    expect(screen.getByText("(أنت)")).toBeInTheDocument();
    expect(screen.getByTestId("map-scene")).toHaveAttribute("dir", "ltr"); // geography is not mirrored
  });
});

describe("Island", () => {
  it("shows costs from the economy, the placement banner, and the dialog's balance after", async () => {
    serve({
      ...BASE,
      [`GET /api/courses/${C}`]: island,
      [`POST /api/courses/${C}/presence`]: null,
    });
    const user = userEvent.setup();
    const { container } = show(
      <IslandPage />,
      "/worlds/:worldId/courses/:courseId",
      `/worlds/${W}/courses/${C}`,
    );
    expect(await screen.findByText(/3-minute placement quiz/)).toBeInTheDocument();
    const tutor = container.querySelector('[data-building="socratic_tutor"]') as HTMLElement;
    expect(within(tutor).getByText("8")).toBeInTheDocument();
    expect(screen.getByText("Ask 2 · Answer free")).toBeInTheDocument();
    expect(screen.getByText("Weak spot")).toBeInTheDocument();
    expect(screen.getByText(/1 classmate studying Limits/)).toBeInTheDocument();
    await user.click(tutor);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("8 coins")).toBeInTheDocument();
    expect(within(dialog).getByText("12")).toBeInTheDocument(); // 20 - 8, from /api/wallet
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("Placement", () => {
  it("answers 8 cached questions and shows the level", async () => {
    const questions = Array.from({ length: 8 }, (_, i) => ({
      i,
      question: `Question ${i + 1}?`,
      options: ["A", "B", "C", "D"],
    }));
    const calls = serve({
      ...BASE,
      "POST /api/placement/start": { course_id: C, cached: true, cost: 0, job_id: null, questions },
      "POST /api/placement/finish": {
        level: "intermediate",
        correct: 5,
        total: 8,
        percent: 60,
        chapters: [{ chapter_id: "ch1", title: "Limits", correct: 3, asked: 4 }],
      },
    });
    const user = userEvent.setup();
    show(
      <PlacementPage />,
      "/worlds/:worldId/courses/:courseId/placement",
      `/worlds/${W}/courses/${C}/placement`,
    );
    for (let i = 0; i < 8; i++) {
      await screen.findByText(`Question ${i + 1}?`);
      await user.click(screen.getByRole("radio", { name: "B" }));
      await user.click(screen.getByRole("button", { name: i === 7 ? "See my level" : "Next" }));
    }
    expect(await screen.findByText("Your starting level")).toBeInTheDocument();
    expect(screen.getByText("Intermediate")).toBeInTheDocument();
    expect(screen.getByText("5 of 8 right")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/placement/finish")?.body).toEqual({
      course_id: C,
      answers: [1, 1, 1, 1, 1, 1, 1, 1],
    });
  });
});
