import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DocumentOut, IndexingOut, WorldOut } from "@/api/client";
import i18n from "@/i18n";
import type { Language } from "@/i18n/languages";
import { CreateOrJoinPage } from "./CreateOrJoinPage";
import { IndexingPage } from "./IndexingPage";

const W = "11111111-1111-1111-1111-111111111111";
const C = "22222222-2222-2222-2222-222222222222";
const CH = "33333333-3333-3333-3333-333333333333";

const world: WorldOut = {
  id: W,
  name: "Engineering 2B",
  join_code: "OLIVE-7Q2",
  is_creator: true,
  members: 1,
  courses: [
    {
      id: C,
      name: "Calculus I",
      color_key: "island-1",
      exam_date: null,
      chapters: [{ id: CH, idx: 1, title: "Limits", documents: [] }],
    },
  ],
};

const doc = (over: Partial<DocumentOut> = {}): DocumentOut => ({
  id: "44444444-4444-4444-4444-444444444444",
  chapter_id: CH,
  filename: "Calculus_Ch1_Limits.pdf",
  kind: "pdf",
  size: 2_400_000,
  status: "uploaded",
  progress: 0,
  detail: null,
  page_count: null,
  error: null,
  created_at: "2026-10-29T10:00:00Z",
  ...over,
});

const indexing = (over: Partial<IndexingOut> = {}): IndexingOut => ({
  world_id: W,
  name: "Engineering 2B",
  join_code: "OLIVE-7Q2",
  percent: 40,
  eta_s: 180,
  done: false,
  chapters: [
    {
      chapter_id: CH,
      course_id: C,
      course_name: "Calculus I",
      idx: 1,
      title: "Limits",
      state: "in_progress",
      documents: [
        doc({
          status: "parsing",
          progress: 40,
          page_count: 30,
          detail: { key: "page", n: 12, of: 30 },
        }),
      ],
    },
  ],
  quizzes: { state: "waiting", ready: 0 },
  ...over,
});

type Routes = Record<string, unknown>;

function serve(routes: Routes) {
  const calls: { key: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${new URL(url).pathname}`;
    calls.push({ key, init });
    const body = routes[key];
    return new Response(JSON.stringify(body ?? { detail: "errors.world_not_found" }), {
      status: body === undefined ? 404 : 200,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function show(ui: ReactElement, { lang = "en", route = "/" }: { lang?: Language; route?: string }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={i18n.cloneInstance({ lng: lang })}>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path="/worlds/new" element={ui} />
            <Route path="/worlds/:worldId/indexing" element={<IndexingPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Create-world wizard", () => {
  it("walks name → courses → chapters, creates the world once, then shows uploads", async () => {
    const calls = serve({
      [`POST /api/worlds`]: { ...world, courses: [] },
      [`POST /api/worlds/${W}/courses`]: world.courses[0],
      [`GET /api/worlds/${W}`]: world,
      [`GET /api/system/status`]: { upload_max_mb: 50 },
    });
    const user = userEvent.setup();
    show(<CreateOrJoinPage />, { route: "/worlds/new" });

    expect(screen.getByText("Creating · step 1 of 4")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Usually your class or group name.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("World name"), "Engineering 2B");
    await user.click(screen.getByRole("button", { name: "Next" }));

    await user.type(screen.getByLabelText("Course name"), "Calculus I");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("group", { name: "Chapters of Calculus I" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Chapter title"), "Limits");
    expect(calls.filter((c) => c.init?.method === "POST")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Add material for Calculus I")).toBeInTheDocument();
    const posts = calls.filter((c) => c.init?.method === "POST");
    expect(posts.map((c) => c.key)).toEqual(["POST /api/worlds", `POST /api/worlds/${W}/courses`]);
    expect(JSON.parse(String(posts[1]!.init!.body))).toEqual({
      name: "Calculus I",
      chapters: ["Limits"],
    });
    expect(
      screen.getByText("Up to 50 MB per file. We read photos of the board too."),
    ).toBeInTheDocument();
    expect(screen.getByText(/1 more course to fill/)).toBeInTheDocument();
  });

  it("uploads files and shows each one's state; rejects unsupported types locally", async () => {
    const calls = serve({
      [`POST /api/worlds`]: { ...world, courses: [] },
      [`POST /api/worlds/${W}/courses`]: world.courses[0],
      [`GET /api/worlds/${W}`]: world,
      [`GET /api/system/status`]: { upload_max_mb: 50 },
      [`POST /api/chapters/${CH}/documents`]: { document: doc(), job_id: "j1", reused: false },
      [`GET /api/worlds/${W}/indexing`]: indexing(),
    });
    const user = userEvent.setup({ applyAccept: false });
    const { container } = show(<CreateOrJoinPage />, { route: "/worlds/new" });
    await user.type(screen.getByLabelText("World name"), "Engineering 2B");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(screen.getByLabelText("Course name"), "Calculus I");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(screen.getByLabelText("Chapter title"), "Limits");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Add material for Calculus I");

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, [
      new File(["%PDF"], "Calculus_Ch1_Limits.pdf", { type: "application/pdf" }),
      new File(["MZ"], "game.exe"),
    ]);
    const pdfRow = (await screen.findByText("Calculus_Ch1_Limits.pdf")).closest("li")!;
    await waitFor(() =>
      expect(within(pdfRow).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40"),
    );
    expect(within(pdfRow).getByText(/Chapter 1 · Limits/)).toBeInTheDocument();
    const exeRow = screen.getByText("game.exe").closest("li")!;
    expect(within(exeRow).getByText(/file type isn't supported/)).toBeInTheDocument();
    expect(calls.filter((c) => c.key.includes("/documents"))).toHaveLength(1); // .exe never sent
    expect(screen.getByText(/0 more courses|Every course has material/)).toBeInTheDocument();
  });

  it("shows the server's error key when the join code is unknown", async () => {
    serve({});
    const user = userEvent.setup();
    show(<CreateOrJoinPage />, { route: "/worlds/new" });
    await user.type(screen.getByLabelText("Invite code"), "olive 222");
    await user.click(screen.getByRole("button", { name: "Join" }));
    expect(await screen.findByText(/doesn't exist, or you're not a member/)).toBeInTheDocument();
  });
});

describe("Indexing screen", () => {
  it("shows the file being read, chapter rows, ETA and the class code", async () => {
    serve({ [`GET /api/worlds/${W}/indexing`]: indexing() });
    show(<CreateOrJoinPage />, { route: `/worlds/${W}/indexing` });
    expect(await screen.findByText("Raising your islands")).toBeInTheDocument();
    expect(screen.getByText("Calculus_Ch1_Limits.pdf · page 12 of 30")).toBeInTheDocument();
    expect(screen.getByText("About 3 minutes left")).toBeInTheDocument();
    const row = screen.getByText("Reading Chapter 1 · Limits").closest("li")!;
    expect(within(row).getByText("In progress")).toBeInTheDocument();
    expect(within(row).getByText(/1 file · 30 pages/)).toBeInTheDocument();
    expect(screen.getByTestId("join-code")).toHaveTextContent("OLIVE-7Q2");
    expect(screen.getByRole("progressbar", { name: "Indexing progress" })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
  });

  it("copies the code", async () => {
    serve({ [`GET /api/worlds/${W}/indexing`]: indexing() });
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    show(<CreateOrJoinPage />, { route: `/worlds/${W}/indexing` });
    await user.click(await screen.findByRole("button", { name: "Copy code" }));
    expect(writeText).toHaveBeenCalledWith("OLIVE-7Q2");
    expect(await screen.findByRole("button", { name: "Copied!" })).toBeInTheDocument();
  });

  it("renders in Arabic when done", async () => {
    serve({
      [`GET /api/worlds/${W}/indexing`]: indexing({
        done: true,
        percent: 100,
        eta_s: 0,
        quizzes: { state: "done", ready: 1 },
        chapters: [
          { ...indexing().chapters[0]!, state: "done", documents: [doc({ status: "ready" })] },
        ],
      }),
    });
    show(<CreateOrJoinPage />, { lang: "ar", route: `/worlds/${W}/indexing` });
    expect(await screen.findAllByText("جزرك جاهزة!")).not.toHaveLength(0);
    expect(screen.getByText("ادعُ صفّك")).toBeInTheDocument();
    expect(screen.getByText("قراءة الفصل 1 · Limits").closest("li")).toHaveTextContent("تم");
  });
});
