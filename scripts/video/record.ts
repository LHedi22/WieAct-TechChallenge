/**
 * Demo-video shots. Each test = one shot = one clip in docs/report/video/raw/NN-name.webm
 * (+ NN-name.marks.json with in-clip timestamps the editor uses). Run one at a time, in order:
 *   cd scripts/video && npx playwright test -c playwright.config.ts -g "^.*01-landing"
 * Data comes from scripts/video/prepare.py (see NOTES.md for the order).
 */
import { test } from "@playwright/test";
import {
  API,
  Marks,
  PASSWORD,
  ROOT,
  WEB,
  apiJson,
  attempt,
  click,
  closeBrowser,
  hover,
  login,
  newShot,
  saveState,
  sleep,
  sql,
  state,
  typeIn,
} from "./lib";
import path from "node:path";

test.afterAll(async () => closeBrowser());

const NICK = {
  A: "Explorer-Amira",
  B: "Explorer-Youssef",
  C: "Explorer-Sami",
  D: "Explorer-Lina",
};

test("01-landing", async () => {
  await attempt("01-landing", async () => {
    const s = await newShot("01-landing", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await page.goto(WEB + "/");
    await page.waitForLoadState("networkidle");
    await page.mouse.move(700, 450);
    await sleep(1500);
    m.mark("start");
    for (const l of ["fr", "ar", "ar-TN", "en"]) {
      await click(page, page.locator(`[role=group] button[lang="${l}"]`).first(), 200);
      m.mark(l);
      await sleep(l === "ar" ? 2200 : 1600);
    }
    m.mark("end");
    m.save();
    await s.finish();
  });
});

test("02-onboarding", async () => {
  await attempt("02-onboarding", async (n) => {
    // A retry needs the nickname free again: rename an earlier attempt's account.
    if (n > 1 || sql(`select count(*) from users where nickname='${NICK.A}'`) !== "0") {
      sql(`update users set nickname = 'old-' || substr(md5(random()::text),1,6) where nickname='${NICK.A}'`);
    }
    const s = await newShot("02-onboarding", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await page.goto(WEB + "/signup");
    await page.waitForLoadState("networkidle");
    await page.mouse.move(720, 300);
    m.mark("signup");
    await typeIn(page, page.getByLabel("Nickname").first(), NICK.A, 70);
    await typeIn(page, page.getByLabel("Password").first(), PASSWORD, 30);
    await click(page, page.getByRole("button", { name: /Create my account/i }));
    await page.waitForURL(/\/welcome/);
    await sleep(800);
    // Profile: optional → Continue
    await click(page, page.getByRole("button", { name: /^Continue$/ }));
    // Style test: 4 scenario cards
    m.mark("style");
    const picks = [1, 0, 1, 3];
    for (let q = 0; q < 4; q++) {
      const radios = page.getByRole("radio");
      await radios.first().waitFor();
      await sleep(q === 0 ? 1600 : 500);
      await click(page, radios.nth(picks[q]), 350);
      await sleep(q === 0 ? 900 : 300);
      await click(page, page.getByRole("button", { name: /^Continue$/ }), 150);
    }
    // Goals → Continue
    await page.getByText("What are you aiming for?").waitFor();
    await sleep(700);
    await click(page, page.getByRole("button", { name: /^Continue$/ }));
    // Result card + avatar
    await page.getByText(/You learn best with/).waitFor();
    m.mark("result");
    await hover(page, page.getByText(/You learn best with/));
    await sleep(2200);
    const surprise = page.getByRole("button", { name: /Surprise me/i });
    m.mark("avatar");
    await click(page, surprise, 300);
    await sleep(1100);
    await click(page, surprise, 200);
    await sleep(1100);
    await click(page, surprise, 200);
    await sleep(1600);
    m.mark("avatarEnd");
    await click(page, page.getByRole("button", { name: /^Continue$/ }));
    await click(page, page.getByRole("button", { name: /Set sail/i }));
    await page.waitForURL(/\/worlds\//);
    await sleep(1500);
    m.mark("end");
    m.save();
    await s.finish();
  });
});

/** API sign-up + onboarding finished (not recorded). Idempotent: logs in if the account exists. */
async function ensureUser(page: import("@playwright/test").Page, nick: string, lang: string) {
  const r = await page.request.post(`${API}/api/auth/signup`, {
    data: { nickname: nick, password: PASSWORD, ui_language: lang },
  });
  if (r.status() !== 201) await login(page, nick);
  await apiJson(page, "PUT", "/api/profile", {
    languages: [lang === "ar-TN" ? "ar" : lang],
    style_visual: 30, style_practice: 30, style_listening: 20, style_teaching: 20,
    finish: true,
  });
}

const SAMPLES = path.join(__dirname, "samples");

test("03-world", async () => {
  await attempt("03-world", async () => {
    const a = await newShot("03a-create", { lang: "en" });
    const ma = new Marks(a.name);
    const pa = a.page;
    await login(pa, NICK.A);
    await pa.goto(WEB + "/worlds/new");
    await pa.waitForLoadState("load");
    await pa.mouse.move(900, 300);
    await sleep(1000);
    ma.mark("name");
    await typeIn(pa, pa.getByLabel("World name"), "Engineering 2B", 70);
    await click(pa, pa.getByRole("button", { name: /^Next$/ }));
    ma.mark("courses");
    await typeIn(pa, pa.getByLabel("Course name").first(), "Calculus I", 60);
    await click(pa, pa.getByRole("button", { name: /Add course/ }));
    await typeIn(pa, pa.getByLabel("Course name").nth(1), "Data Structures", 60);
    await click(pa, pa.getByRole("button", { name: /^Next$/ }));
    ma.mark("chapters");
    // Chapters: course 1 gets two, course 2 one
    const ch = () => pa.getByLabel("Chapter title");
    await typeIn(pa, ch().first(), "Limits and derivatives", 45);
    await click(pa, pa.getByRole("button", { name: /Add chapter/ }).first());
    await typeIn(pa, ch().nth(1), "Integrals", 45);
    await typeIn(pa, ch().nth(2), "Stacks and queues", 45);
    await click(pa, pa.getByRole("button", { name: /^Next$/ }));
    ma.mark("upload");
    await sleep(800);
    await hover(pa, pa.getByText(/browse/).first());
    await pa.locator('input[type="file"]').setInputFiles(path.join(SAMPLES, "Calculus_I_Limits_Derivatives.pdf"));
    await sleep(2500);
    await click(pa, pa.getByRole("tab", { name: /Data Structures/ }));
    await hover(pa, pa.getByText(/browse/).first());
    await pa.locator('input[type="file"]').setInputFiles(path.join(SAMPLES, "DataStructures_Stacks_Queues.pptx"));
    await sleep(3000);
    await click(pa, pa.getByRole("button", { name: /Build my islands/ }));
    await pa.waitForURL(/indexing/, { timeout: 120_000 });
    ma.mark("indexing");
    const worldId = pa.url().match(/worlds\/([0-9a-f-]{36})/)![1];
    const code = sql(`select join_code from worlds where id='${worldId}'`);
    saveState({ worldId, code });
    await hover(pa, pa.getByText(code.slice(0, 5)).first());

    // B (Arabic) joins with the code in a second browser while A's islands are raised
    const b = await newShot("03b-join", { lang: "ar" });
    const mb = new Marks(b.name);
    const pb = b.page;
    await ensureUser(pb, NICK.B, "ar");
    await pb.goto(WEB + "/worlds/new");
    await pb.waitForLoadState("load");
    await pb.mouse.move(700, 300);
    await sleep(1200);
    mb.mark("type");
    await typeIn(pb, pb.getByLabel("رمز الدعوة"), code, 110);
    await sleep(400);
    await click(pb, pb.getByRole("button", { name: /^انضم$/ }));
    await pb.waitForURL(/\/worlds\/[0-9a-f-]{36}$/, { timeout: 60_000 });
    mb.mark("map");
    await pb.waitForLoadState("load");
    await pb.mouse.move(600, 500, { steps: 25 });
    await sleep(6000);
    mb.mark("end");
    mb.save();
    await b.finish();

    // A waits for indexing, then opens the map
    const go = pa.getByRole("link", { name: /Go to my world/ }).or(pa.getByRole("button", { name: /Go to my world/ }));
    await pa.getByText("Your islands are ready!").waitFor({ timeout: 15 * 60_000 });
    ma.mark("ready");
    await sleep(1500);
    await click(pa, go.first());
    await pa.waitForURL(/\/worlds\/[0-9a-f-]{36}$/);
    await pa.waitForLoadState("load");
    await pa.mouse.move(700, 500, { steps: 25 });
    await sleep(4000);
    ma.mark("end");
    ma.save();
    await a.finish();
  });
});

/** Re-shoot of B's join once the islands are raised (attempt 1's 03a clip is kept). */
test("03b-join", async () => {
  await attempt("03b-join", async () => {
    const code = state().code;
    const b = await newShot("03b-join", { lang: "ar" });
    const mb = new Marks(b.name);
    const pb = b.page;
    await ensureUser(pb, NICK.B, "ar");
    await pb.goto(WEB + "/worlds/new");
    await pb.getByLabel("رمز الدعوة").waitFor();
    await pb.mouse.move(700, 300);
    await sleep(1200);
    mb.mark("type");
    await typeIn(pb, pb.getByLabel("رمز الدعوة"), code, 110);
    await sleep(400);
    await click(pb, pb.getByRole("button", { name: /^انضم$/ }));
    await pb.waitForURL(/\/worlds\/[0-9a-f-]{36}$/, { timeout: 60_000 });
    mb.mark("map");
    await pb.getByTestId("map-scene").waitFor();
    await pb.mouse.move(600, 500, { steps: 25 });
    await sleep(6000);
    mb.mark("end");
    mb.save();
    await b.finish();
  });
});

/** A: indexing page (islands ready) → Go to my world → the same map. */
test("03c-amap", async () => {
  await attempt("03c-amap", async () => {
    const st = state();
    const a = await newShot("03c-amap", { lang: "en" });
    const pa = a.page;
    await login(pa, NICK.A);
    await pa.goto(`${WEB}/worlds/${st.worldId}/indexing`);
    const go = pa.getByRole("link", { name: /Go to my world/ }).or(pa.getByRole("button", { name: /Go to my world/ }));
    await go.first().waitFor();
    await pa.mouse.move(500, 400);
    await sleep(1500);
    await click(pa, go.first());
    await pa.getByTestId("map-scene").waitFor();
    await pa.mouse.move(700, 500, { steps: 25 });
    await sleep(6000);
    await a.finish();
  });
});

function chapters() {
  const wid = state().worldId;
  const rows = sql(
    `select co.name, ch.id, ch.idx, co.id from chapters ch join courses co on co.id=ch.course_id where co.world_id='${wid}' order by co.name, ch.idx`,
  )
    .split("\n")
    .map((r) => r.split("\t"));
  const find = (course: string, idx: number) => rows.find((r) => r[0] === course && r[2] === String(idx))!;
  const calc1 = find("Calculus I", 1);
  const ds1 = find("Data Structures", 1);
  return { wid, calc: calc1[3], calc1: calc1[1], ds: ds1[3], ds1: ds1[1] };
}

/** Answer key + whether each hint gives the answer away (staging only: answers never reach the browser). */
function answerKey(attemptId: string): { right: number; leaks: boolean }[] {
  const raw = sql(
    `select qs.questions from quiz_attempts a join quiz_sets qs on qs.id=a.quiz_set_id where a.id='${attemptId}'`,
  );
  const norm = (x: string) => String(x).toLowerCase().replace(/\s+/g, "");
  return (JSON.parse(raw) as { answer_index: number; options: string[]; hint?: string }[]).map((q) => {
    const right = norm(q.options[q.answer_index]);
    return { right: q.answer_index, leaks: !q.hint || norm(q.hint).includes(right) };
  });
}

/** 06 + 07: building dialog → loading stages in the queue (+ Class Wisdom tip) → quiz with a hint. */
test("06-quiz", async () => {
  await attempt("06-quiz", async () => {
    const c = chapters();
    const s = await newShot("06-quiz", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await login(page, NICK.A);
    // classmates who started something a moment earlier (real jobs, so A's quiz waits in line)
    const side = await (await import("./lib")).getBrowser().then((b) => b.newContext());
    const sp = await side.newPage();
    await page.goto(`${WEB}/worlds/${c.wid}/courses/${c.calc}`);
    await page.getByTestId("island-scene").waitFor();
    await page.mouse.move(600, 450);
    await sleep(1500);
    m.mark("island");
    await click(page, page.locator('[data-building="quiz_hall"]'));
    m.mark("dialog");
    await sleep(1200);
    await click(page, page.locator('label:has(input[name="level"][value="intermediate"])'));
    await sleep(1200);
    const enter = page.getByRole("button", { name: /^Enter$/ });
    await hover(page, enter);
    await sleep(800);
    await sleep(400);
    await enter.click();
    m.mark("loading");
    await page.mouse.move(720, 500, { steps: 20 });
    await page.getByRole("button", { name: /^Check$/ }).waitFor({ timeout: 20 * 60_000 });
    m.mark("quiz");
    await side.close();
    const attemptId = page.url().match(/quiz\/([0-9a-f-]{36})/)![1];
    const key = answerKey(attemptId);
    saveState({ quizAttempt: attemptId });
    // every option, disabled or not, so an index is the option index
    const options = page.locator("main li button");
    const check = page.getByRole("button", { name: /^Check$/ });
    const retry = page.getByRole("button", { name: /Try again/ });
    const next = page.getByRole("button", { name: /Next question/ });
    const results = page.getByRole("button", { name: /See my results/ });
    // wrong answers only where the hint doesn't give the answer away (at most two)
    // an attempt left by an interrupted take resumes where it stopped
    const start = Number(sql(`select current from quiz_attempts where id='${attemptId}'`)) || 0;
    const wrongs = key.map((k, i) => (!k.leaks && i >= start ? i : -1)).filter((i) => i >= 0).slice(0, 2);
    saveState({ quizWrongs: wrongs, quizLeaks: key.filter((k) => k.leaks).length });
    for (let q = start; q < key.length; q++) {
      await options.first().waitFor();
      const slow = q <= (wrongs[0] ?? 0);
      await sleep(slow ? 1500 : 400);
      const n = await options.count();
      const wrong = wrongs.includes(q);
      await click(page, options.nth(wrong ? (key[q].right + 1) % n : key[q].right), slow ? 400 : 150);
      await click(page, check, 150);
      if (wrong) {
        await retry.waitFor();
        m.mark(`hint${q}`);
        await hover(page, page.getByText(/Not quite/));
        await sleep(q === wrongs[0] ? 3500 : 1200);
        await click(page, options.nth(key[q].right), 300);
        await click(page, retry, 200);
        m.mark(`second${q}`);
        await sleep(q === wrongs[0] ? 3500 : 1200);
      } else {
        await sleep(slow ? 1200 : 400);
      }
      if (await results.isVisible().catch(() => false)) break;
      await click(page, next, 150);
    }
    await click(page, results);
    await page.getByText("Your score").waitFor({ timeout: 120_000 });
    m.mark("results");
    await sleep(2000);
    for (const t of [/Your next step/, /Turn these into flashcards/]) {
      const l = page.getByText(t).first();
      if (await l.isVisible().catch(() => false)) {
        await hover(page, l, 30);
        await sleep(2200);
      }
    }
    const tip = page.getByTestId("wisdom-tip");
    if (await tip.count()) {
      await hover(page, tip.first(), 30);
      await sleep(2500);
    }
    m.mark("end");
    m.save();
    await s.finish();
  });
});

/** Island → building → dialog → Enter (the dialog shows level + cost). */
async function enterBuilding(
  page: import("@playwright/test").Page,
  building: string,
  pause = 1800,
  level?: string,
) {
  await click(page, page.locator(`[data-building="${building}"]`));
  const enter = page.getByRole("button", { name: /^Enter$/ });
  await enter.waitFor();
  await sleep(pause / 2);
  if (level) {
    await click(page, page.locator(`label:has(input[name="level"][value="${level}"])`));
  }
  await sleep(pause / 2 + (level ? 1200 : 0));
  await click(page, enter);
}

async function openIsland(page: import("@playwright/test").Page, course: "calc" | "ds" = "calc") {
  const c = chapters();
  await page.goto(`${WEB}/worlds/${c.wid}/courses/${c[course]}`);
  await page.getByTestId("island-scene").waitFor();
  await page.mouse.move(600, 450);
  await sleep(1200);
}

test("08-tutor", async () => {
  await attempt("08-tutor", async () => {
    const s = await newShot("08-tutor", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await login(page, NICK.A);
    await openIsland(page);
    await enterBuilding(page, "socratic_tutor", 1200);
    const box = page.getByPlaceholder(/Type your thinking/);
    await box.waitFor({ timeout: 15 * 60_000 });
    const stuck = page.getByRole("button", { name: /^I'm stuck$/ });
    await stuck.waitFor();
    await page.waitForFunction(() => {
      const b = [...document.querySelectorAll("button")].find((x) => x.textContent?.trim() === "I'm stuck");
      return b && !(b as HTMLButtonElement).disabled;
    }, null, { timeout: 15 * 60_000 });
    m.mark("ready");
    await sleep(2500);
    await typeIn(page, box, "I think the limit of sin(x)/x at 0 is 0, because sin(0) = 0.", 45);
    await click(page, page.getByRole("button", { name: /^Send$/ }));
    const idle = () =>
      page.waitForFunction(() => {
        const b = [...document.querySelectorAll("button")].find((x) => x.textContent?.trim() === "I'm stuck");
        return b && !(b as HTMLButtonElement).disabled;
      }, null, { timeout: 15 * 60_000 });
    await sleep(1500);
    await idle();
    m.mark("reply1");
    await sleep(4000);
    for (const n of [1, 2]) {
      await click(page, stuck, 400);
      m.mark(`stuck${n}`);
      await sleep(1500);
      await idle();
      m.mark(`reply-stuck${n}`);
      await page.mouse.move(700, 500, { steps: 15 });
      await sleep(4500);
    }
    const ideas = page.getByText("Ideas you've found");
    if (await ideas.isVisible().catch(() => false)) {
      await hover(page, ideas, 25);
      await sleep(3000);
    }
    m.mark("end");
    m.save();
    await s.finish();
  });
});

test("09-studio", async () => {
  await attempt("09-studio", async () => {
    const s = await newShot("09-studio", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await login(page, NICK.A);
    await openIsland(page);
    await enterBuilding(page, "study_studio", 1500, "intermediate");
    await page.getByTestId("notes").waitFor({ timeout: 120_000 });
    m.mark("notes");
    await sleep(1500);
    await page.mouse.move(700, 500, { steps: 15 });
    await page.mouse.wheel(0, 350);
    await sleep(1500);
    await page.mouse.wheel(0, 350);
    await sleep(1500);
    await page.mouse.wheel(0, -700);
    await click(page, page.getByRole("tab", { name: /Flashcards/ }));
    await page.getByTestId("flashcard").waitFor();
    m.mark("cards");
    await hover(page, page.getByTestId("flashcard"));
    await sleep(1800);
    for (const g of ["2", "3"]) {
      await page.keyboard.press("Space");
      await sleep(2200);
      await page.keyboard.press(g);
      await sleep(1500);
    }
    // mind map: the local compact model's maps never validated (see NOTES.md), so it isn't shown
    await sleep(1500);
    m.mark("end");
    m.save();
    await s.finish();
  });
});

test("11-audio", async () => {
  await attempt("11-audio", async () => {
    const s = await newShot("11-audio", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await login(page, NICK.A);
    await openIsland(page);
    await enterBuilding(page, "audio_studio", 1500, "intermediate");
    await page.getByTestId("audio-player").or(page.getByTestId("transcript-only")).first().waitFor({ timeout: 120_000 });
    m.mark("player");
    const voices = await page.evaluate(() => speechSynthesis.getVoices().length);
    saveState({ audioVoices: voices });
    await sleep(1500);
    const play = page.getByRole("button", { name: /Play|Listen/i }).first();
    if (await play.isVisible().catch(() => false)) {
      await click(page, play);
      m.mark("play");
    }
    await page.mouse.move(800, 600, { steps: 20 });
    await sleep(9000);
    m.mark("end");
    m.save();
    await s.finish();
  });
});

const TEACH_ANSWER =
  "Plugging in 0 gives 0/0, which is not a value: it only says we must look closer. For small x, sin x is almost exactly x, so sin(x)/x gets closer and closer to 1. The squeeze theorem makes it exact: cos x <= sin(x)/x <= 1 near 0, and both sides go to 1.";

test("12-teachback", async () => {
  await attempt("12-teachback", async () => {
    const c = chapters();
    const s = await newShot("12-teachback", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await login(page, NICK.A);
    await openIsland(page);
    await enterBuilding(page, "teachback_arena", 1500);
    const q = page.getByText(/sin x\)\/x as x approaches 0/).first();
    await q.waitFor({ timeout: 60_000 });
    m.mark("feed");
    await sleep(1200);
    await click(page, q);
    const box = page.getByLabel(/Explain it to your classmate/);
    await box.waitFor();
    await sleep(1000);
    m.mark("typing");
    await typeIn(page, box, TEACH_ANSWER, 18);
    await click(page, page.getByRole("button", { name: /Send my explanation/ }));
    m.mark("grading");
    await page.mouse.move(700, 600, { steps: 15 });
    await page.getByText("/100 AI score").first().waitFor({ timeout: 15 * 60_000 });
    m.mark("score");
    await hover(page, page.getByText("/100 AI score").first(), 20);
    await sleep(3500);
    // C, who asked, pins the answer from another browser; A's page polls and shows it
    const side = await (await import("./lib")).getBrowser().then((b) => b.newContext());
    const sp = await side.newPage();
    await login(sp, NICK.C);
    const aId = sql(
      `select a.id from peer_answers a join users u on u.id=a.author_id where u.nickname='${NICK.A}' order by a.id desc limit 1`,
    );
    const pin = await apiJson(sp, "POST", `/api/arena/answers/${aId}/pin`);
    await side.close();
    saveState({ pinStatus: pin.status });
    await page.getByText(/Pinned as best/).first().waitFor({ timeout: 60_000 });
    m.mark("pinned");
    await hover(page, page.getByText(/Pinned as best/).first(), 20);
    await sleep(2500);
    await hover(page, page.locator("header").getByText(/coins/).first(), 25);
    await sleep(2500);
    m.mark("end");
    m.save();
    await s.finish();
  });
});

/** Classmates (not recorded) keep the island open so "On this island now" is real. */
async function classmatesOnIsland(nicks: string[]) {
  const c = chapters();
  const b = await (await import("./lib")).getBrowser();
  const ctxs = [];
  for (const n of nicks) {
    const ctx = await b.newContext({ viewport: { width: 1280, height: 800 } });
    const p = await ctx.newPage();
    await login(p, n);
    await p.goto(`${WEB}/worlds/${c.wid}/courses/${c.calc}`);
    ctxs.push(ctx);
  }
  return async () => {
    for (const x of ctxs) await x.close();
  };
}

test("05-island", async () => {
  await attempt("05-island", async () => {
    const done = await classmatesOnIsland([NICK.B, NICK.C]);
    await sleep(4000);
    const s = await newShot("05-island", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await login(page, NICK.A);
    await openIsland(page);
    m.mark("island");
    for (const b of ["quiz_hall", "socratic_tutor", "study_studio", "audio_studio", "teachback_arena"]) {
      await hover(page, page.locator(`[data-building="${b}"]`), 14);
      await sleep(700);
    }
    const now = page.getByText("On this island now").first();
    if (await now.isVisible().catch(() => false)) {
      await hover(page, now, 20);
      m.mark("now");
      await sleep(2500);
    }
    const weak = page.getByText(/mastery/i).first();
    if (await weak.isVisible().catch(() => false)) {
      await hover(page, weak, 20);
      await sleep(2000);
    }
    m.mark("end");
    m.save();
    await s.finish();
    await done();
  });
});

test("04-map", async () => {
  await attempt("04-map", async () => {
    const c = chapters();
    const s = await newShot("04-map", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await login(page, NICK.A);
    await page.goto(`${WEB}/worlds/${c.wid}`);
    await page.getByTestId("map-scene").waitFor();
    await page.mouse.move(500, 450);
    await sleep(1500);
    m.mark("map");
    const zin = page.getByRole("button", { name: "Zoom in" });
    if (await zin.isVisible().catch(() => false)) {
      await click(page, zin);
      await sleep(900);
      await click(page, zin, 100);
      await sleep(1300);
      await click(page, page.getByRole("button", { name: "Zoom out" }));
      await sleep(400);
      await click(page, page.getByRole("button", { name: "Zoom out" }), 100);
      await sleep(900);
    }
    m.mark("topbar");
    for (const t of [/coins/, /points/, /streak/]) {
      const l = page.locator("header").getByText(t).first();
      if (await l.isVisible().catch(() => false)) {
        await hover(page, l, 14);
        await sleep(900);
      }
    }
    m.mark("daily");
    const daily = page.getByTestId("daily-card").first();
    if (await daily.isVisible().catch(() => false)) {
      await hover(page, daily, 20);
      await sleep(2200);
    }
    const cls = page.getByText("Your class").first();
    if (await cls.isVisible().catch(() => false)) {
      await hover(page, cls, 20);
      await sleep(1200);
    }
    m.mark("leaderboard");
    await page.goto(`${WEB}/worlds/${c.wid}/leaderboard`);
    await page.waitForLoadState("load");
    await page.mouse.move(700, 400, { steps: 20 });
    await sleep(3500);
    m.mark("end");
    m.save();
    await s.finish();
  });
});

test("10-phone", async () => {
  await attempt("10-phone", async () => {
    const c = chapters();
    const s = await newShot("10-phone", { lang: "ar", phone: true });
    const m = new Marks(s.name);
    const { page } = s;
    await login(page, NICK.B);
    await page.goto(`${WEB}/worlds/${c.wid}/courses/${c.calc}`);
    await page.getByTestId("island-scene").waitFor();
    await sleep(1500);
    m.mark("island");
    await page.locator('[data-building="study_studio"]').scrollIntoViewIfNeeded();
    await sleep(800);
    await click(page, page.locator('[data-building="study_studio"]'));
    m.mark("dialog");
    const enter = page.getByRole("button", { name: /^دخول$|^ادخل$/ }).or(page.locator("[role=dialog] button").last());
    await enter.first().waitFor();
    await sleep(2800);
    await click(page, enter.first());
    await page.getByTestId("notes").waitFor({ timeout: 120_000 });
    m.mark("notes");
    await sleep(2000);
    await page.mouse.wheel(0, 400);
    await sleep(1500);
    await page.mouse.wheel(0, -400);
    await sleep(800);
    const tabs = page.getByRole("tab");
    if ((await tabs.count()) >= 3) {
      await click(page, tabs.nth(2));
      await sleep(3000);
    }
    m.mark("end");
    m.save();
    await s.finish();
  });
});

/** 13: the stats page (stats_page.py stats) then two seconds of the offline banner. */
test("13-stats", async () => {
  await attempt("13-stats", async () => {
    const { execFileSync } = await import("node:child_process");
    const py = (args: string[]) =>
      execFileSync("C:/Python311/python.exe", [path.join(__dirname, "stats_page.py"), ...args], { cwd: ROOT, encoding: "utf8" });
    py(["stats"]);
    const c = chapters();
    const s = await newShot("13-stats", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await page.goto("file:///" + path.join(ROOT, "docs/report/video/raw/stats.html").split(path.sep).join("/"));
    await page.mouse.move(300, 300);
    await sleep(1000);
    m.mark("stats");
    for (const t of ["Compact share", "Cache hits", "Repeated identical", "Model routing", "Calls per task"]) {
      await hover(page, page.getByText(t).first(), 18);
      await sleep(1100);
    }
    await sleep(800);
    try {
      py(["offline", "on"]);
      await sleep(4000);
      await login(page, NICK.A);
      await page.goto(`${WEB}/worlds/${c.wid}/courses/${c.calc}`);
      await page.getByTestId("island-scene").waitFor();
      m.mark("offline");
      await page.mouse.move(700, 120, { steps: 20 });
      await sleep(4000);
    } finally {
      py(["offline", "auto"]);
    }
    m.mark("end");
    m.save();
    await s.finish();
  });
});

/** 06: building dialog (level + coins) → generate → loading stages, queue position, Class Wisdom tip. */
test("06-loading", async () => {
  await attempt("06-loading", async () => {
    const c = chapters();
    const s = await newShot("06-loading", { lang: "en" });
    const m = new Marks(s.name);
    const { page } = s;
    await login(page, NICK.A);
    await openIsland(page);
    m.mark("island");
    await enterBuilding(page, "study_studio", 2600);
    const make = page.getByRole("button", { name: /^Make it$/ });
    await make.waitFor({ timeout: 60_000 });
    m.mark("panel");
    await hover(page, page.getByTestId("generate-panel"), 20);
    await sleep(1800);
    // a classmate started a quiz a moment earlier (a real job), so A's pack waits in line
    const side = await (await import("./lib")).getBrowser().then((b) => b.newContext());
    const sp = await side.newPage();
    await login(sp, NICK.C);
    await apiJson(sp, "POST", "/api/quiz/start", { chapter_id: c.ds1, level: "beginner" });
    await side.close();
    await click(page, make);
    m.mark("loading");
    await page.mouse.move(720, 520, { steps: 20 });
    await sleep(70_000);
    m.mark("end");
    m.save();
    await s.finish();
  });
});
