/** Helpers for the demo-video recorder: contexts that record a clip, a visible cursor, human pacing. */
import { type Browser, type BrowserContext, type Locator, type Page, chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export const WEB = process.env.WEB_URL ?? "http://localhost:5173";
export const API = process.env.API_URL ?? "http://localhost:8000";
export const ROOT = path.resolve(__dirname, "../..");
export const RAW = path.join(ROOT, "docs/report/video/raw");
export const STATE_FILE = path.join(__dirname, "state.json");
export const PASSWORD = "explorer-demo-2026";

export type Lang = "en" | "fr" | "ar" | "ar-TN";

export function state(): Record<string, any> {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch {
    return {};
  }
}
export function saveState(patch: Record<string, unknown>) {
  fs.writeFileSync(STATE_FILE, JSON.stringify({ ...state(), ...patch }, null, 2));
}

/** psql against the compose db (read-mostly staging helpers; never prints secrets). */
export function sql(query: string): string {
  return execFileSync(
    "docker",
    ["compose", "exec", "-T", "db", "psql", "-U", "lw", "-d", "learningworld", "-At", "-F", "\t", "-c", query],
    { cwd: ROOT, encoding: "utf8" },
  ).trim();
}

let browser: Browser | null = null;
export async function getBrowser() {
  if (!browser) {
    browser = await chromium.launch({
      headless: process.env.HEADED ? false : true,
      args: ["--host-resolver-rules=MAP localhost 127.0.0.1", "--force-color-profile=srgb", "--hide-scrollbars"],
    });
  }
  return browser;
}
export async function closeBrowser() {
  await browser?.close();
  browser = null;
}

/** Injected before any page script: hide dev-only controls, draw a cursor dot. */
const INIT = `(() => {
  const css = \`[data-testid="provider-switch"],[data-testid="provider-badge"]{display:none!important}
  #__vid_cursor{position:fixed;z-index:2147483647;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;
    background:rgba(255,196,0,.55);border:2px solid rgba(20,20,20,.85);pointer-events:none;
    box-shadow:0 0 0 3px rgba(255,255,255,.6);transition:transform .12s ease;left:-50px;top:-50px}
  #__vid_cursor.down{transform:scale(.7);background:rgba(255,120,0,.75)}\`;
  const add = () => {
    if (document.getElementById("__vid_cursor")) return;
    const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    const c = document.createElement("div"); c.id = "__vid_cursor"; document.body.appendChild(c);
    const p = window.__vidPos; if (p) { c.style.left = p[0] + "px"; c.style.top = p[1] + "px"; }
  };
  document.addEventListener("mousemove", (e) => {
    window.__vidPos = [e.clientX, e.clientY];
    const c = document.getElementById("__vid_cursor"); if (c) { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }
  }, true);
  document.addEventListener("mousedown", () => document.getElementById("__vid_cursor")?.classList.add("down"), true);
  document.addEventListener("mouseup", () => document.getElementById("__vid_cursor")?.classList.remove("down"), true);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add); else add();
  new MutationObserver(add).observe(document.documentElement, { childList: true, subtree: false });
})();`;

export interface Shot {
  ctx: BrowserContext;
  page: Page;
  name: string;
  /** Close the context and move its video to raw/<name>.webm. */
  finish: () => Promise<string>;
}

export async function newShot(
  name: string,
  opts: { lang?: Lang; phone?: boolean; record?: boolean } = {},
): Promise<Shot> {
  const b = await getBrowser();
  const phone = !!opts.phone;
  const viewport = phone ? { width: 390, height: 844 } : { width: 1440, height: 900 };
  const size = phone ? { width: 468, height: 1012 } : { width: 1728, height: 1080 };
  const tmp = path.join(RAW, "_tmp", name + "-" + Date.now());
  const record = opts.record !== false;
  const ctx = await b.newContext({
    viewport,
    deviceScaleFactor: Number(process.env.DSF ?? (phone ? 3 : 2)),
    isMobile: phone,
    hasTouch: phone,
    locale: opts.lang === "ar-TN" ? "ar-TN" : (opts.lang ?? "en"),
    timezoneId: "Africa/Tunis",
    ...(record ? { recordVideo: { dir: tmp, size } } : {}),
  });
  await ctx.addInitScript(INIT);
  if (opts.lang) {
    await ctx.addInitScript((l) => {
      try {
        const cur = JSON.parse(localStorage.getItem("lw-ui") || "null");
        if (!cur) localStorage.setItem("lw-ui", JSON.stringify({ state: { language: l, reducedMotion: false }, version: 0 }));
      } catch {
        /* private mode */
      }
    }, opts.lang);
  }
  const page = await ctx.newPage();
  const finish = async () => {
    const video = page.video();
    await ctx.close();
    if (!video) return "";
    const out = path.join(RAW, `${name}.webm`);
    await video.saveAs(out);
    fs.rmSync(tmp, { recursive: true, force: true });
    return out;
  };
  return { ctx, page, name, finish };
}

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Move the visible cursor to an element's centre with intermediate steps. */
export async function hover(page: Page, l: Locator, steps = 18) {
  await l.scrollIntoViewIfNeeded();
  const box = await l.boundingBox();
  if (!box) throw new Error("no bounding box");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps });
}

/** Human-looking click: move, short pause, click. */
export async function click(page: Page, l: Locator, pause = 250) {
  await l.waitFor({ state: "visible" });
  await hover(page, l);
  await sleep(pause);
  await l.click();
}

export async function typeIn(page: Page, l: Locator, text: string, delay = 60) {
  await click(page, l, 150);
  await l.fill("");
  await l.pressSequentially(text, { delay });
}

/** Log in through the API with the context's cookie jar. */
export async function login(page: Page, nickname: string, password = PASSWORD) {
  const r = await page.request.post(`${API}/api/auth/login`, { data: { nickname, password } });
  if (r.status() >= 300) throw new Error(`login ${nickname}: ${r.status()} ${await r.text()}`);
}

export async function apiJson(page: Page, method: string, url: string, data?: unknown) {
  const r = await page.request.fetch(`${API}${url}`, { method, data });
  const ct = r.headers()["content-type"] ?? "";
  return { status: r.status(), body: ct.includes("json") ? await r.json() : await r.text() };
}

/** Run a shot up to 3 times; log the attempt used. */
export async function attempt(name: string, fn: (n: number) => Promise<void>) {
  const log = path.join(RAW, "attempts.log");
  for (let n = 1; n <= 3; n++) {
    try {
      await fn(n);
      fs.appendFileSync(log, `${new Date().toISOString()} ${name}: ok on attempt ${n}\n`);
      return;
    } catch (e) {
      fs.appendFileSync(log, `${new Date().toISOString()} ${name}: attempt ${n} failed: ${String(e).slice(0, 300)}\n`);
      if (n === 3) throw e;
    }
  }
}

/** Write a marker file with in-clip timestamps (seconds) used by the editor for trims/speed. */
export class Marks {
  private t0 = Date.now();
  private m: Record<string, number> = {};
  constructor(private name: string) {}
  reset() {
    this.t0 = Date.now();
  }
  mark(key: string) {
    this.m[key] = Math.round((Date.now() - this.t0) / 100) / 10;
  }
  save() {
    fs.writeFileSync(path.join(RAW, `${this.name}.marks.json`), JSON.stringify(this.m, null, 2));
  }
}
