import { type APIRequestContext, type Page, type TestInfo, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

export const API = process.env.API_URL ?? "http://localhost:8000";
export const LANGS = ["en", "fr", "ar", "ar-TN"] as const;
export type Lang = (typeof LANGS)[number];

const I18N_DIR = path.resolve(__dirname, "../../../frontend/src/i18n");
const dicts: Record<string, Record<string, unknown>> = {};
for (const l of LANGS) dicts[l] = JSON.parse(fs.readFileSync(path.join(I18N_DIR, `${l}.json`), "utf8"));

function lookup(d: Record<string, unknown>, key: string): string | undefined {
  let cur: unknown = d;
  for (const part of key.split(".")) {
    if (cur && typeof cur === "object" && part in (cur as object)) cur = (cur as Record<string, unknown>)[part];
    else return undefined;
  }
  return typeof cur === "string" ? cur : undefined;
}

/** Translated string with the i18next fallback chain (ar-TN → ar → en); {vars} cut off. */
export function t(lang: Lang, key: string): string {
  const chain = lang === "ar-TN" ? ["ar-TN", "ar", "en"] : [lang, "en"];
  for (const l of chain) {
    const v = lookup(dicts[l], key);
    if (v !== undefined) return v;
  }
  throw new Error(`missing i18n key ${key}`);
}

/** Literal part of a string before the first {placeholder} — usable as a substring match. */
export function stem(lang: Lang, key: string): string {
  return t(lang, key).split("{")[0].trim();
}

export function rx(s: string): RegExp {
  return new RegExp(s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
}

/** Every top-level i18n namespace: a visible "quiz.next"-like token is a raw key. */
const NAMESPACES = Object.keys(dicts.en).concat(["errors"]);
const RAW_KEY = new RegExp(`\\b(${NAMESPACES.join("|")})\\.[a-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)*\\b`);

export interface Problems {
  console: string[];
  pageErrors: string[];
  http: string[];
}

/** Attach listeners that collect console errors, uncaught exceptions and unexpected 4xx/5xx. */
export function guard(page: Page, allowHttp: RegExp[] = []): Problems {
  const p: Problems = { console: [], pageErrors: [], http: [] };
  page.on("console", (m) => {
    if (m.type() === "error") p.console.push(m.text().slice(0, 300));
  });
  page.on("pageerror", (e) => p.pageErrors.push(String(e).slice(0, 300)));
  page.on("response", (r) => {
    const u = r.url();
    if (r.status() >= 400 && !allowHttp.some((a) => a.test(`${r.status()} ${u}`))) {
      p.http.push(`${r.status()} ${r.request().method()} ${u.replace(/https?:\/\/[^/]+/, "")}`);
    }
  });
  return p;
}

/** Fail on console errors, uncaught exceptions, unexpected HTTP errors. */
export function assertClean(p: Problems, info: TestInfo) {
  info.annotations.push({ type: "problems", description: JSON.stringify(p) });
  // Browsers log failed requests as console errors; those are already reported under http.
  const consoleOnly = p.console.filter((c) => !/Failed to load resource/.test(c));
  expect.soft(p.pageErrors, "uncaught exceptions").toEqual([]);
  expect.soft(consoleOnly, "console errors").toEqual([]);
  expect.soft(p.http, "unexpected HTTP errors").toEqual([]);
}

/** Raw i18n keys, unresolved {placeholders} and horizontal scroll on the current screen. */
export async function screenChecks(page: Page, label: string) {
  const text = await page.locator("body").innerText();
  const raw = text.match(RAW_KEY);
  expect.soft(raw?.[0] ?? null, `${label}: raw i18n key visible`).toBeNull();
  const ph = text.match(/\{[a-zA-Z_]+\}|\{\{[a-zA-Z_]+\}\}/);
  expect.soft(ph?.[0] ?? null, `${label}: unresolved placeholder`).toBeNull();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect.soft(overflow, `${label}: horizontal scroll (px)`).toBeLessThanOrEqual(1);
}

export async function setLanguage(page: Page, lang: Lang) {
  await page.addInitScript((l) => {
    try {
      window.localStorage.setItem("lw-ui", JSON.stringify({ state: { language: l, reducedMotion: true }, version: 0 }));
    } catch {
      /* private mode */
    }
  }, lang);
}

export function nick(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
}

/** Sign up through the API with the page's cookie jar (cookies are per host, not per port). */
export async function apiSignup(req: APIRequestContext, lang: Lang, nickname = nick("e2e")) {
  const r = await req.post(`${API}/api/auth/signup`, {
    data: { nickname, password: "audit-pass-123", ui_language: lang },
  });
  expect(r.status(), await r.text()).toBe(201);
  return nickname;
}

export async function apiJson(req: APIRequestContext, method: string, url: string, data?: unknown) {
  const r = await req.fetch(`${API}${url}`, { method, data });
  const body = r.headers()["content-type"]?.includes("json") ? await r.json() : await r.text();
  return { status: r.status(), body };
}

export async function waitJob(req: APIRequestContext, jobId: string, timeoutMs = 120_000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const { body } = await apiJson(req, "GET", `/api/jobs/${jobId}`);
    if (["done", "failed", "cancelled"].includes(body.status)) return body;
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error(`job ${jobId} not done in ${timeoutMs} ms`);
}

/** API fast path to an onboarded student in the demo world with placement done. */
export async function readyStudent(req: APIRequestContext, lang: Lang) {
  const nickname = await apiSignup(req, lang);
  await apiJson(req, "PUT", "/api/profile", { languages: [lang === "ar-TN" ? "ar" : lang], finish: true });
  const j = await apiJson(req, "POST", "/api/worlds/join", { code: "OLIVE-7Q2" });
  expect(j.status, JSON.stringify(j.body)).toBe(200);
  const world = j.body;
  for (const c of world.courses) {
    const s = await apiJson(req, "POST", "/api/placement/start", { course_id: c.id });
    if (s.body?.job_id) await waitJob(req, s.body.job_id);
    const set = await apiJson(req, "GET", `/api/placement/${c.id}`);
    const qs = set.body?.questions ?? [];
    const answers = qs.map(() => 0);
    await apiJson(req, "POST", "/api/placement/finish", { course_id: c.id, answers });
  }
  return { nickname, world };
}

/** Demo coin pack (clearly labelled demo purchase) so every paid building can open in a sweep. */
export async function buyCoins(req: APIRequestContext) {
  const r = await apiJson(req, "POST", "/api/wallet/demo-purchase", { product: "coin_pack" });
  expect(r.status, JSON.stringify(r.body)).toBeLessThan(300);
}

export async function shot(page: Page, info: TestInfo, name: string) {
  const dir = path.resolve(__dirname, "../../artifacts/screenshots");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${name}-${info.project.name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  return file;
}
