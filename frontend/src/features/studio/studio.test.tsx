import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CardQueue, ClassPool, Studio } from "@/api/client";
import i18n from "@/i18n";
import type { Language } from "@/i18n/languages";
import { PoolCard } from "@/features/pool/PoolCard";
import { StudioPage } from "./StudioPage";

type Handler = (body: unknown) => [number, unknown];

function serve(routes: Record<string, unknown>) {
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

const PATH = "/worlds/:worldId/courses/:courseId/studio";
function show(ui: ReactElement, route: string, lang: Language = "en") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n.cloneInstance({ lng: lang })}>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={PATH} element={ui} />
            <Route path="*" element={ui} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

const ROUTE = "/worlds/w1/courses/c1/studio?chapter=ch1&level=intermediate";
const POOL: ClassPool = {
  balance: 20,
  max_contribution: 50,
  recent: [{ nickname: "Owl7", coins: 6 }],
};

function studio(over: Partial<Studio> = {}): Studio {
  return {
    chapter_id: "ch1",
    chapter_title: "Derivatives",
    level: "intermediate",
    language: "en",
    notes: {
      title: "Derivatives",
      sections: [{ heading: "Slope", points: ["$f'(a)$ is the slope"], refs: ["page:12"] }],
      key_terms: [{ term: "Tangent", meaning: "touches the curve" }],
    },
    map: {
      root: "Derivatives",
      branches: [
        { label: "Slope", children: ["tangent"] },
        { label: "Rules", children: ["product", "chain"] },
      ],
    },
    missing: [],
    pending_job_id: null,
    cards: { new: 2, learning: 0, review: 0, total: 2 },
    pool_balance: 20,
    cost: 0,
    cached: true,
    ...over,
  };
}

const QUEUE: CardQueue = {
  cards: [
    {
      id: "k1",
      front: "What does f'(a) measure?",
      back: "How fast f changes at a.",
      concept: "slope",
      source: "deck",
      stage: "new",
      intervals: { again: 60, good: 600, easy: 259200 },
    },
    {
      id: "k2",
      front: "Chain rule?",
      back: "f(g(x))' = f'(g(x)) g'(x)",
      concept: "chain",
      source: "deck",
      stage: "new",
      intervals: { again: 60, good: 600, easy: 259200 },
    },
  ],
  counts: { new: 2, learning: 0, review: 0, total: 2 },
  next_due_at: null,
};

function base(over: Partial<Studio> = {}) {
  return {
    "GET /api/courses/c1": {
      name: "Calculus I",
      chapters: [{ id: "ch1", idx: 2, title: "Derivatives" }],
    },
    "GET /api/studio/ch1": studio(over),
    "GET /api/studio/ch1/cards": QUEUE,
    "GET /api/worlds/w1/pool": POOL,
    "GET /api/wallet": { coins: 20 },
    "GET /api/wisdom": { tips: [] },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("Study Studio", () => {
  it("shows notes with refs, then the mind map tab", async () => {
    serve(base());
    show(<StudioPage />, ROUTE);
    const notes = await screen.findByTestId("notes");
    expect(within(notes).getByText("Slope")).toBeInTheDocument();
    expect(within(notes).getByText("Page")).toBeInTheDocument();
    expect(within(notes).getByText("Tangent")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Mind map" }));
    const map = await screen.findByTestId("mind-map");
    expect(within(map).getByText("Rules")).toBeInTheDocument();
    expect(within(map).getByText("chain")).toBeInTheDocument();
  });

  it("flips with Space and grades with the keyboard, showing the server's intervals", async () => {
    const calls = serve({
      ...base(),
      "POST /api/studio/cards/k1/review": () => [
        200,
        { card_id: "k1", due_at: "2099-01-01T00:00:00Z", interval_s: 600 },
      ],
    });
    show(<StudioPage />, `${ROUTE}&tab=flashcards`);
    expect(await screen.findByText("Card 1 of 2")).toBeInTheDocument();
    expect(screen.queryByText("Answer")).not.toBeInTheDocument();
    await userEvent.keyboard(" ");
    expect(screen.getByText("How fast f changes at a.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Good.*in 10 min/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Easy.*in 3 days/ })).toBeInTheDocument();
    await userEvent.keyboard("2");
    expect(await screen.findByText("Card 2 of 2")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/studio/cards/k1/review")?.body).toEqual({
      grade: "good",
    });
  });

  it("offers to make the pack, paid by me or by the Class Pool", async () => {
    const calls = serve({
      ...base({
        notes: null,
        map: null,
        missing: ["notes", "flashcards", "map"],
        cards: { new: 0, learning: 0, review: 0, total: 0 },
        cost: 15,
        cached: false,
      }),
      "POST /api/studio/ch1/generate": () => [200, { job_id: "j1", cost: 15, cached: false }],
      "GET /api/jobs/j1": {
        id: "j1",
        status: "running",
        stage: "writing_notes",
        stages: ["reading_chapter", "writing_notes", "making_flashcards", "drawing_map"],
        queue_position: null,
        eta_s: null,
        quick_mode: false,
        result: null,
        error: null,
      },
    });
    show(<StudioPage />, ROUTE);
    const panel = await screen.findByTestId("generate-panel");
    await userEvent.click(within(panel).getByRole("radio", { name: /Class Pool \(20 coins\)/ }));
    await userEvent.click(within(panel).getByRole("button", { name: "Make it" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "POST /api/studio/ch1/generate")?.body).toEqual({
        level: "intermediate",
        pay: "pool",
      }),
    );
    expect(await screen.findByText("Writing the notes")).toBeInTheDocument();
  });

  it("opens the mind map tab in Arabic", async () => {
    serve(base());
    show(<StudioPage />, `${ROUTE}&tab=map`, "ar");
    expect(await screen.findByRole("tab", { name: "الخريطة الذهنية" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(await screen.findByTestId("mind-map")).toBeInTheDocument();
  });
});

describe("Class Pool card", () => {
  it("shows the balance and recent gifts by nickname, and adds coins", async () => {
    const calls = serve({
      "GET /api/worlds/w1/pool": POOL,
      "POST /api/worlds/w1/pool": () => [200, { ...POOL, balance: 25 }],
    });
    show(<PoolCard worldId="w1" />, "/");
    const card = await screen.findByTestId("pool-card");
    expect(within(card).getByText("Owl7")).toBeInTheDocument();
    expect(within(card).getByText("gave 6 coins")).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "Add coins" }));
    await waitFor(() =>
      expect(calls.find((c) => c.key === "POST /api/worlds/w1/pool")?.body).toEqual({ amount: 5 }),
    );
  });
});
