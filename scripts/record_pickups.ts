/**
 * Pickup clips for the demo video (raw footage, no captions). One test per clip:
 *   cd scripts/video && node node_modules/@playwright/test/cli.js test -c ../record_pickups.config.ts -g clip1
 * Order: prep → clip1 → clip2 → clip3. Output: docs/video/pickups/*.webm (+ .mp4, .log.json).
 * The admin switch is flipped through POST/DELETE /api/admin/force-quick from inside the backend
 * container (the token stays in the container's environment; nothing admin is on camera).
 */
import { type Browser, type Locator, type Page, chromium, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const WEB = "http://localhost:5173";
const API = "http://localhost:8000";
const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "docs/video/pickups");
const PASSWORD = "explorer-demo-2026";
const WORLD_CODE = "TIDES-BBW";
const NEW_USER = "Explorer-Nadia";
const ASKER = "Explorer-Sami";
const ANSWERER = "Explorer-Amira";
const QUESTION = "Can a limit exist at a point where the function itself is not defined? Why?";
const ANSWER =
  "Yes. A limit only looks at the values near the point, not at the point itself. For example (x^2 - 4)/(x - 2) is undefined at x = 2, but for every x near 2 it equals x + 2, so the limit is 4.";

fs.mkdirSync(OUT, { recursive: true });

function sql(q: string): string {
  return execFileSync(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", "lw", "-d", "learningworld", "-At", "-F", "\t", "-c", q],
    { cwd: ROOT, encoding: "utf8" },
  ).trim();
}

/** Admin API call made inside the backend container; prints only the status and body. */
function adminCall(method: "POST" | "DELETE", body?: object): string {
  const code = `
import json, os, urllib.request
req = urllib.request.Request("http://localhost:8000/api/admin/force-quick", method=${JSON.stringify(method)},
    data=${body ? `json.dumps(${JSON.stringify(body)}).encode()` : "None"},
    headers={"X-Admin-Token": os.environ["ADMIN_TOKEN"], "X-Admin-Action": "1", "Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=30) as r:
    print(r.status, r.read().decode())
`;
  return execFileSync("docker", ["compose", "exec", "-T", "backend", "python", "-c", code], {
    cwd: ROOT,
    encoding: "utf8",
  }).trim();
}

const CURSOR = `(() => {
  const css = \`[data-testid="provider-switch"]{display:none!important}
  #__pc{position:fixed;z-index:2147483647;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;
   background:#F5C542;border:2px solid #1E2A38;box-sizing:border-box;pointer-events:none;
   transition:transform .15s ease;left:-60px;top:-60px}
  #__pc.down{transform:scale(1.45)}\`;
  const add = () => {
    if (document.getElementById("__pc")) return;
    const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    const c = document.createElement("div"); c.id = "__pc"; document.body.appendChild(c);
    const p = window.__pcPos; if (p) { c.style.left = p[0] + "px"; c.style.top = p[1] + "px"; }
  };
  document.addEventListener("mousemove", (e) => {
    window.__pcPos = [e.clientX, e.clientY];
    const c = document.getElementById("__pc"); if (c) { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }
  }, true);
  document.addEventListener("mousedown", () => document.getElementById("__pc")?.classList.add("down"), true);
  document.addEventListener("mouseup", () => setTimeout(() => document.getElementById("__pc")?.classList.remove("down"), 140), true);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add); else add();
  new MutationObserver(add).observe(document.documentElement, { childList: true });
})();`;

let browser: Browser | null = null;
async function getBrowser() {
  browser ??= await chromium.launch({ args: ["--host-resolver-rules=MAP localhost 127.0.0.1", "--hide-scrollbars"] });
  return browser;
}
test.afterAll(async () => {
  await browser?.close();
  browser = null;
});

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

class Clip {
  created = Date.now();
  t0 = 0;
  marks: { t: number; what: string }[] = [];
  constructor(public page: Page, public name: string, public finish: () => Promise<string>) {}
  /** Call when the page is ready; the first action comes 1 s later (trim point for the mp4). */
  async start() {
    this.t0 = Date.now();
    await sleep(1000);
  }
  mark(what: string) {
    this.marks.push({ t: Math.round((Date.now() - this.t0) / 100) / 10, what });
  }
}

async function newClip(name: string, record = true): Promise<Clip> {
  const b = await getBrowser();
  const tmp = path.join(OUT, "_tmp", `${name}-${Date.now()}`);
  const ctx = await b.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    reducedMotion: "no-preference",
    locale: "en",
    timezoneId: "Africa/Tunis",
    ...(record ? { recordVideo: { dir: tmp, size: { width: 1440, height: 900 } } } : {}),
  });
  await ctx.addInitScript(CURSOR);
  await ctx.addInitScript(() => {
    try {
      localStorage.setItem("lw-ui", JSON.stringify({ state: { language: "en", reducedMotion: false }, version: 0 }));
    } catch {
      /* private mode */
    }
  });
  const page = await ctx.newPage();
  const clip = new Clip(page, name, async () => {
    const v = page.video();
    await ctx.close();
    if (!v) return "";
    const webm = path.join(OUT, `${name}.webm`);
    await v.saveAs(webm);
    const trim = Math.max(0, (clip.t0 - clip.created) / 1000);
    fs.writeFileSync(path.join(OUT, `${name}.log.json`), JSON.stringify({ trim_start_s: trim, marks: clip.marks }, null, 2));
    return webm;
  });
  return clip;
}

async function login(page: Page, nickname: string) {
  const r = await page.request.post(`${API}/api/auth/login`, { data: { nickname, password: PASSWORD } });
  if (r.status() >= 300) throw new Error(`login ${nickname}: ${r.status()}`);
}
async function api(page: Page, method: string, url: string, data?: unknown) {
  const r = await page.request.fetch(`${API}${url}`, { method, data });
  const txt = await r.text();
  return { status: r.status(), body: txt ? JSON.parse(txt) : null };
}
async function waitJob(page: Page, id: string, ms = 15 * 60_000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const { body } = await api(page, "GET", `/api/jobs/${id}`);
    if (["done", "failed", "cancelled"].includes(body?.status)) return body;
    await sleep(2000);
  }
  throw new Error("job timeout " + id);
}

/** Pause ~600 ms before each click, steps: 25 moves. */
async function moveTo(page: Page, l: Locator) {
  await l.waitFor({ state: "visible" });
  await l.scrollIntoViewIfNeeded();
  const b = (await l.boundingBox())!;
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 25 });
}
async function click(page: Page, l: Locator) {
  await moveTo(page, l);
  await sleep(600);
  await l.click();
}

function ids() {
  const wid = sql(`select id from worlds where join_code='${WORLD_CODE}'`);
  const calc = sql(`select id from courses where world_id='${wid}' and name='Calculus I'`);
  const ch1 = sql(`select id from chapters where course_id='${calc}' and idx=1`);
  return { wid, calc, ch1 };
}

test("prep", async () => {
  const { wid, ch1 } = ids();
  const c = await newClip("prep", false);
  const p = c.page;
  // fresh explorer: learning-style test finished, in the world, no placement yet
  const s = await p.request.post(`${API}/api/auth/signup`, {
    data: { nickname: NEW_USER, password: PASSWORD, ui_language: "en" },
  });
  if (s.status() !== 201) await login(p, NEW_USER);
  await api(p, "PUT", "/api/profile", {
    languages: ["en"], style_visual: 25, style_practice: 40, style_listening: 10, style_teaching: 25, finish: true,
  });
  await api(p, "POST", "/api/worlds/join", { code: WORLD_CODE });
  // clip 3: a question from the asker with a classmate's scored answer, not pinned yet
  await login(p, ASKER);
  let qid = sql(`select id from peer_questions where text='${QUESTION.replace(/'/g, "''")}' limit 1`);
  if (!qid) {
    const r = await api(p, "POST", "/api/arena/questions", { chapter_id: ch1, text: QUESTION });
    await waitJob(p, r.body.job_id);
    qid = r.body.question_id;
  }
  await login(p, ANSWERER);
  const has = sql(`select count(*) from peer_answers where question_id='${qid}'`);
  if (has === "0") {
    const r = await api(p, "POST", `/api/arena/questions/${qid}/answers`, { text: ANSWER });
    console.log("answer job", (await waitJob(p, r.body.job_id)).status);
  }
  console.log(sql(`select status, ai_score, ai_confidence from peer_answers where question_id='${qid}'`));
  fs.writeFileSync(path.join(OUT, "_prep.json"), JSON.stringify({ wid, qid }));
  await c.finish();
});

/** Placement answers that land on intermediate, with question 2 wrong (staging read of the key). */
function placementPlan(courseId: string): number[] {
  const qs = JSON.parse(
    sql(`select questions from placement_sets where course_id='${courseId}' and language='en' limit 1`),
  ) as { answer_index: number; options: string[]; difficulty?: string }[];
  const w = (q: { difficulty?: string }) =>
    ({ beginner: 1, intermediate: 2, advanced: 3 })[q.difficulty ?? "intermediate"] ?? 2;
  const total = qs.reduce((a, q) => a + w(q), 0);
  let earned = 0;
  return qs.map((q, i) => {
    const right = i !== 1 && (earned + w(q)) / total <= 0.62;
    if (right) earned += w(q);
    return right ? q.answer_index : (q.answer_index + 1) % q.options.length;
  });
}

async function tutorIdle(p: Page) {
  await sleep(800);
  await p.waitForFunction(
    () => {
      const b = [...document.querySelectorAll("button")].find((x) => x.textContent?.trim() === "I'm stuck");
      return !!b && !(b as HTMLButtonElement).disabled;
    },
    null,
    { timeout: 10 * 60_000 },
  );
}

test("clip1", async () => {
  const { wid, calc } = ids();
  const plan = placementPlan(calc);
  const who = process.env.CLIP1_USER ?? "Explorer-Rania";
  const c = await newClip("clip1_placement");
  const p = c.page;
  // a fresh explorer: learning-style test done, in the world, no level yet
  const su = await p.request.post(`${API}/api/auth/signup`, { data: { nickname: who, password: PASSWORD, ui_language: "en" } });
  if (su.status() !== 201) await login(p, who);
  await api(p, "PUT", "/api/profile", {
    languages: ["en"], style_visual: 25, style_practice: 40, style_listening: 10, style_teaching: 25, finish: true,
  });
  await api(p, "POST", "/api/worlds/join", { code: WORLD_CODE });
  await p.goto(`${WEB}/worlds/${wid}/courses/${calc}`);
  const startBtn = p
    .getByRole("button", { name: /Start placement quiz/ })
    .or(p.getByRole("link", { name: /Start placement quiz/ }))
    .first();
  await startBtn.waitFor();
  await p.mouse.move(700, 520);
  await c.start();
  c.mark("island, locked, placement banner");
  await moveTo(p, startBtn);
  c.mark("hover Start placement quiz");
  await sleep(1200);
  await click(p, startBtn);
  const radios = p.locator("label:has(input[type=radio])");
  const next = p.getByRole("button", { name: /^Next$/ });
  const finish = p.getByRole("button", { name: /See my level/ });
  for (let i = 0; i < plan.length; i++) {
    await radios.first().waitFor();
    const fast = i >= 3;
    if (i === 3) c.mark("CUT START (questions 4-8 fast-pathed)");
    if (!fast) await sleep(1400);
    if (i === 0) c.mark("question 1 shown");
    const opt = radios.nth(plan[i]);
    if (fast) await opt.click();
    else {
      await click(p, opt);
      c.mark(`question ${i + 1} answered${i === 1 ? " (wrong)" : ""}`);
      await sleep(700);
    }
    if (await finish.isVisible().catch(() => false)) {
      if (fast) await finish.click();
      else await click(p, finish);
      break;
    }
    if (fast) await next.click();
    else await click(p, next);
  }
  await p.getByText("Your starting level").waitFor({ timeout: 120_000 });
  c.mark("CUT END · result: starting level shown");
  const lvl = (await p.locator("main").innerText()).match(/Beginner|Intermediate|Advanced/i)?.[0] ?? "?";
  c.mark(`level = ${lvl}`);
  await p.mouse.move(720, 450, { steps: 25 });
  await sleep(2000);
  const toIsland = p
    .getByRole("link", { name: /Go to the island/ })
    .or(p.getByRole("button", { name: /Go to the island/ }))
    .first();
  await click(p, toIsland);
  await p.getByTestId("island-scene").waitFor();
  c.mark("island: buildings unlocked at that level");
  await p.mouse.move(600, 450, { steps: 25 });
  await sleep(2000);
  await click(p, p.locator('[data-building="quiz_hall"]'));
  await p.getByRole("button", { name: /^Enter$/ }).waitFor();
  c.mark("Quiz Hall dialog: level from placement");
  await moveTo(p, p.locator("label").filter({ hasText: /From your placement/ }).first());
  await sleep(2000);
  c.mark("end");
  await sleep(2000);
  await c.finish();
});

test("clip2", async () => {
  const { wid, calc, ch1 } = ids();
  // pre-run the tutor's plan off camera so the session page opens instantly
  const prep = await newClip("clip2_prep", false);
  await login(prep.page, NEW_USER);
  const st = await api(prep.page, "POST", "/api/tutor/start", { chapter_id: ch1, level: "intermediate" });
  console.log("tutor start", JSON.stringify(st.body));
  if (st.body?.job_id) await waitJob(prep.page, st.body.job_id);
  const sessionId = st.body.session_id;
  await prep.finish();
  const since = sql("select now()::text");
  console.log("force quick on:", adminCall("POST", { minutes: 15 }));
  try {
    const c = await newClip("clip2_quickmode");
    const p = c.page;
    await login(p, NEW_USER);
    await p.goto(`${WEB}/worlds/${wid}/courses/${calc}/tutor/${sessionId}`);
    const box = p.getByPlaceholder(/Type your thinking/);
    const stuck = p.getByRole("button", { name: /^I'm stuck$/ });
    await box.waitFor();
    await tutorIdle(p);
    await p.mouse.move(700, 400);
    await c.start();
    c.mark("tutor session open");
    await click(p, box);
    await box.pressSequentially("Plugging in x = 2 gives 0/0, so I think this limit just does not exist.", { delay: 45 });
    await click(p, p.getByRole("button", { name: /^Send$/ }));
    c.mark("wrong idea sent");
    await tutorIdle(p);
    c.mark("reply 1");
    await sleep(1200);
    await click(p, stuck);
    c.mark("I'm stuck (1)");
    await tutorIdle(p);
    c.mark("reply 2");
    await sleep(1200);
    await click(p, stuck);
    c.mark("I'm stuck (2): escalation, forced Quick mode");
    await tutorIdle(p);
    const badge = p.getByText("Quick mode · faster model while it's busy").last();
    await badge.waitFor({ timeout: 30_000 });
    c.mark("reply 3 arrives with Quick mode badge");
    // scroll the conversation to the newest reply, like a student would, then point at its badge
    await p.mouse.move(560, 520, { steps: 25 });
    for (let k = 0; k < 4; k++) {
      await p.mouse.wheel(0, 260);
      await sleep(150);
    }
    await sleep(600);
    const bb = (await badge.boundingBox())!;
    await p.mouse.move(bb.x + bb.width / 2, Math.min(bb.y + bb.height + 18, 880), { steps: 25 });
    await sleep(2500);
    c.mark("end");
    await sleep(2000);
    await c.finish();
  } finally {
    console.log("force quick off:", adminCall("DELETE"));
  }
  console.log(
    sql(`select l.ts::time, l.task_kind, l.model_tier, l.pattern, l.fallback, l.forced, l.status_code
         from ai_call_log l join jobs j on j.id=l.job_id join users u on u.id=j.user_id
         where u.nickname='${NEW_USER}' and l.ts > '${since}' order by l.ts`),
  );
});

test("clip3", async () => {
  const { wid, calc, ch1 } = ids();
  const c = await newClip("clip3_pin");
  const p = c.page;
  await login(p, ASKER);
  await p.goto(`${WEB}/worlds/${wid}/courses/${calc}/arena?chapter=${ch1}`);
  const q = p.getByText(/Can a limit exist at a point/).first();
  await q.waitFor();
  await q.click();
  const pin = p.getByRole("button", { name: /Pin as best answer/ });
  await pin.waitFor();
  await p.mouse.move(800, 300);
  await c.start();
  c.mark("question open, classmate's scored answer visible");
  await sleep(1200);
  await click(p, pin);
  c.mark("Pin clicked");
  const chip = p.getByText(/Pinned best answer/).first();
  await chip.waitFor({ timeout: 30_000 });
  c.mark("Pinned chip shown");
  await moveTo(p, chip);
  await sleep(2000);
  c.mark("end");
  await sleep(2000);
  await c.finish();
});
