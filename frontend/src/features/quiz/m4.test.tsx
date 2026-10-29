import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { IslandOut, QuizAttempt, QuizQuestion, QuizResults, TutorSession } from "@/api/client";
import { MathText } from "@/components";
import i18n from "@/i18n";
import type { Language } from "@/i18n/languages";
import { BuildingDialog } from "@/features/island/BuildingDialog";
import { TutorPage } from "@/features/tutor/TutorPage";
import { QuizAttemptPage } from "./QuizAttemptPage";

const W = "w1";
const C = "c1";
const A = "a1";
const S = "s1";

type Handler = (body: unknown) => [number, unknown];
type Routes = Record<string, unknown | Handler>;

function serve(routes: Routes) {
  const calls: { key: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(url);
      const key = `${init?.method ?? "GET"} ${u.pathname}`;
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ key, body });
      const h = routes[key];
      if (typeof h === "function") {
        const [status, out] = (h as Handler)(body);
        return new Response(JSON.stringify(out), { status });
      }
      if (h === undefined) return new Response('{"detail":"errors.unexpected"}', { status: 404 });
      return new Response(JSON.stringify(h), { status: 200 });
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
            <Route path="*" element={<p>elsewhere</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("MathText", () => {
  it("renders $…$ as LTR math and keeps the rest as text", () => {
    const { container } = render(<MathText text="Compute $x^2$ and $\frac{1}{2}$ now" />);
    const math = container.querySelectorAll("bdi.math");
    expect(math).toHaveLength(2);
    expect(math[0]).toHaveAttribute("dir", "ltr");
    expect(math[0]!.querySelector("sup")).toHaveTextContent("2");
    expect(container).toHaveTextContent("Compute");
    expect(container.textContent).not.toContain("$");
  });
});

const q = (i: number, over: Partial<QuizQuestion> = {}): QuizQuestion => ({
  i,
  question: `Question ${i + 1}?`,
  options: ["A0", "A1", "A2", "A3"],
  status: "pending",
  first: null,
  second: null,
  hint: null,
  answer_index: null,
  explanation: null,
  ...over,
});

const attempt = (qs: QuizQuestion[]): QuizAttempt => ({
  id: A,
  world_id: W,
  course_id: C,
  course_name: "Calculus I",
  chapter_id: "ch1",
  chapter_title: "Limits",
  chapter_idx: 1,
  level: "intermediate",
  status: "in_progress",
  current: 0,
  points: 0,
  questions: qs,
});

describe("Quiz attempt", () => {
  it("wrong → hint → second try → explanation → results with points and next step", async () => {
    const answers: unknown[] = [];
    let first = true;
    const results: QuizResults = {
      attempt_id: A,
      score: 1,
      total: 2,
      points: 5,
      second_tries: 1,
      mastery: 40,
      weak: true,
      missed: [
        {
          i: 1,
          question: "Question 2?",
          status: "skipped",
          yours: null,
          correct: "A3",
          explanation: "Because.",
          concept: "limits",
        },
      ],
      right_concepts: [],
      next_step: {
        kind: "tutor",
        chapter_id: "ch1",
        chapter_title: "Limits",
        level: "intermediate",
        cost: 8,
      },
      tag_job_id: null,
    };
    serve({
      [`GET /api/quiz/attempts/${A}`]: attempt([q(0), q(1)]),
      [`POST /api/quiz/attempts/${A}/answer`]: (body: unknown) => {
        answers.push(body);
        if (first) {
          first = false;
          return [200, q(0, { status: "hint", first: 0, hint: "Factor $x^2-4$ first." })];
        }
        return [
          200,
          q(0, {
            status: "second",
            first: 0,
            second: 2,
            answer_index: 2,
            explanation: "It cancels.",
          }),
        ];
      },
      [`POST /api/quiz/attempts/${A}/skip`]: q(1, {
        status: "skipped",
        answer_index: 3,
        explanation: "Because.",
      }),
      [`POST /api/quiz/attempts/${A}/finish`]: results,
    });
    const user = userEvent.setup();
    show(
      <QuizAttemptPage />,
      "/worlds/:worldId/courses/:courseId/quiz/:attemptId",
      `/worlds/${W}/courses/${C}/quiz/${A}`,
    );

    await screen.findByText("Question 1?");
    await user.click(screen.getByRole("button", { name: /A0/ }));
    await user.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText(/Not quite/)).toBeInTheDocument();
    expect(screen.getByText("Hint")).toBeInTheDocument();
    expect(screen.queryByText("Right answer")).toBeNull(); // no answer before the second try
    expect(screen.getByRole("button", { name: /A0/ })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /A2/ }));
    await user.click(screen.getByRole("button", { name: "Try again · 2nd try" }));
    expect(await screen.findByText(/half the points/)).toBeInTheDocument();
    expect(screen.getByText("It cancels.")).toBeInTheDocument();
    expect(answers).toEqual([
      { q: 0, choice: 0 },
      { q: 0, choice: 2 },
    ]);

    await user.click(screen.getByRole("button", { name: "Next question" }));
    await screen.findByText("Question 2?");
    await user.click(screen.getByRole("button", { name: "Skip this question" }));
    await user.click(await screen.findByRole("button", { name: "See my results" }));

    expect(await screen.findByText("1 thing to look at again")).toBeInTheDocument();
    expect(screen.getByText("+5")).toBeInTheDocument();
    expect(screen.getByText("Weak spot")).toBeInTheDocument();
    const next = screen.getByRole("link", { name: /Go to the Socratic Tutor/ });
    expect(within(next).getByText("8 coins")).toBeInTheDocument();
    expect(next).toHaveAttribute(
      "href",
      `/worlds/${W}/courses/${C}/tutor/new?chapter=ch1&level=intermediate`,
    );
  });
});

const session = (over: Partial<TutorSession> = {}): TutorSession => ({
  id: S,
  world_id: W,
  course_id: C,
  course_name: "Calculus I",
  chapter_id: "ch1",
  chapter_title: "Limits",
  level: "intermediate",
  status: "active",
  goal: "Understand why 0/0 means simplify first",
  ideas: [
    { text: "0/0 is a signal", found: true },
    { text: "Factor and cancel", found: false },
    { text: "Check one-sided limits", found: false },
  ],
  hints_used: 1,
  max_hints: 3,
  turns: [
    {
      role: "tutor",
      text: "What do you get if you plug in $x=2$?",
      quick_mode: false,
      tier: "compact",
    },
    { role: "student", text: "0/0", action: "message", quick_mode: false },
    { role: "tutor", text: "What could you factor?", quick_mode: true, tier: "compact" },
  ],
  pending_job_id: null,
  summary: null,
  ...over,
});

describe("Socratic Tutor", () => {
  it("shows goal, hints used, ideas found and quick mode; sends turns", async () => {
    const calls = serve({
      [`GET /api/tutor/${S}`]: session(),
      [`POST /api/tutor/${S}/turn`]: { session_id: S, job_id: "j9" },
      "GET /api/jobs/j9": { id: "j9", status: "queued", stages: [], stage: null },
    });
    const user = userEvent.setup();
    show(
      <TutorPage />,
      "/worlds/:worldId/courses/:courseId/tutor/:sessionId",
      `/worlds/${W}/courses/${C}/tutor/${S}`,
    );
    expect(await screen.findByText(/Understand why 0\/0/)).toBeInTheDocument();
    expect(screen.getByText("1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Found" })).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "Not yet" })).toHaveLength(2);
    expect(screen.getAllByText(/Quick mode/).length).toBeGreaterThan(0);
    await user.type(screen.getByPlaceholderText(/Type your thinking/), "factor the top?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === `POST /api/tutor/${S}/turn`)?.body).toEqual({
        text: "factor the top?",
        action: "message",
      }),
    );
    await user.click(screen.getByRole("button", { name: "I'm stuck" }));
    expect(calls.filter((c) => c.key === `POST /api/tutor/${S}/turn`).at(-1)?.body).toEqual({
      text: "",
      action: "stuck",
    });
  });

  it("disables hints at 3 and shows the summary when ended (Arabic)", async () => {
    serve({
      [`GET /api/tutor/${S}`]: session({
        hints_used: 3,
        status: "ended",
        summary: {
          summary: "وجدت الفكرة.",
          next_step: "خذ اختبارًا.",
          ideas_found: ["0/0 is a signal"],
        },
      }),
    });
    show(
      <TutorPage />,
      "/worlds/:worldId/courses/:courseId/tutor/:sessionId",
      `/worlds/${W}/courses/${C}/tutor/${S}`,
      "ar",
    );
    expect(await screen.findByText("ملخّص الجلسة")).toBeInTheDocument();
    expect(screen.getByText("وجدت الفكرة.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /أعطني تلميحًا/ })).toBeNull(); // no composer once ended
  });
});

describe("Entry dialog", () => {
  it("asks the server for the quiz price before Confirm", async () => {
    const island: IslandOut = {
      id: C,
      world_id: W,
      name: "Calculus I",
      color_key: "island-1",
      level: "advanced",
      mastery: 0,
      chapters: [{ id: "ch1", idx: 1, title: "Limits", ready: true, mastery: null, weak: false }],
      buildings: [],
      visitors: [],
    };
    serve({
      "GET /api/quiz/price": { cost: 0, cached: true },
      "GET /api/wallet": {
        coins: 20,
        free_today: 20,
        earned: 0,
        purchased: 0,
        points: 0,
        streak: 0,
        refill_at: "2026-10-30T23:00:00Z",
        placeholder: true,
      },
    });
    show(
      <BuildingDialog
        island={island}
        building={{ key: "quiz_hall", cost: 5, free_if_cached: false, answer_cost: null }}
        onClose={() => undefined}
        onConfirm={() => undefined}
      />,
      "/",
      "/",
    );
    expect(await screen.findByText("Your class already made one")).toBeInTheDocument();
    expect(screen.getByText("Free")).toBeInTheDocument();
    expect(screen.getByText("From your placement")).toBeInTheDocument();
  });
});
