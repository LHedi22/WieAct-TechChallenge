import AxeBuilder from "@axe-core/playwright";
import { type Page, type TestInfo, expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { LANGS, type Lang, assertClean, buyCoins, guard, readyStudent, rx, screenChecks, setLanguage, shot, t } from "./lib";

/**
 * Screen sweep: every screen a student reaches, per language × size. On each screen: raw i18n keys,
 * unresolved placeholders, horizontal scroll, dir/lang on <html>, axe (serious + critical), screenshot.
 * Fails on console errors / uncaught exceptions / unexpected HTTP errors.
 */
const AXE_OUT = path.resolve(__dirname, "../../artifacts/axe");
fs.mkdirSync(AXE_OUT, { recursive: true });

async function axe(page: Page, info: TestInfo, screen: string, lang: Lang) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  const rows = bad.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, sample: v.nodes[0]?.target?.join(" ") }));
  fs.writeFileSync(
    path.join(AXE_OUT, `${screen}-${lang}-${info.project.name}.json`),
    JSON.stringify({ screen, lang, project: info.project.name, violations: r.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help, targets: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) })) }, null, 1),
  );
  info.annotations.push({ type: `axe ${screen} ${lang}`, description: JSON.stringify(rows) });
}

async function checkDir(page: Page, lang: Lang) {
  const html = page.locator("html");
  await expect.soft(html).toHaveAttribute("lang", lang);
  await expect.soft(html).toHaveAttribute("dir", lang.startsWith("ar") ? "rtl" : "ltr");
}

const BUILDINGS = [
  { key: "quiz_hall", url: /\/quiz\//, ready: (l: Lang) => t(l, "quiz.check") },
  { key: "socratic_tutor", url: /\/tutor\//, ready: null },
  { key: "study_studio", url: /\/studio/, ready: null },
  { key: "audio_studio", url: /\/audio/, ready: null },
  { key: "teachback_arena", url: /\/arena/, ready: null },
] as const;

for (const lang of LANGS) {
  test(`sweep public screens ${lang}`, async ({ page }, info) => {
    const problems = guard(page, [/401 .*\/api\/auth\/(session|me)/]);
    await setLanguage(page, lang);
    for (const [name, url] of [["landing", "/"], ["signup", "/signup"], ["signin", "/signin"]] as const) {
      await page.goto(url);
      await page.waitForLoadState("load");
      await checkDir(page, lang);
      await screenChecks(page, name);
      await axe(page, info, name, lang);
      await shot(page, info, `sweep-${name}-${lang}`);
    }
    // deep link while signed out → must land on sign-in, not a blank page or a crash
    await page.goto("/worlds/00000000-0000-0000-0000-000000000000");
    await page.waitForLoadState("load");
    await expect.soft(page, "deep link while signed out goes to sign in").toHaveURL(/signin|signup|\/$/);
    assertClean(problems, info);
  });

  test(`sweep student screens ${lang}`, async ({ page }, info) => {
    const problems = guard(page, [/401 .*\/api\/auth\/(session|me)/]);
    await setLanguage(page, lang);
    const { world } = await readyStudent(page.request, lang);
    await buyCoins(page.request);
    const course = world.courses.find((c: { name: string }) => c.name.startsWith("Calculus")) ?? world.courses[0];
    const W = `/worlds/${world.id}`;
    const C = `${W}/courses/${course.id}`;

    const visit = async (name: string, url: string) => {
      await page.goto(url);
      await page.waitForLoadState("load");
      await page.waitForTimeout(800);
      await checkDir(page, lang);
      await screenChecks(page, name);
      await axe(page, info, name, lang);
      await shot(page, info, `sweep-${name}-${lang}`);
    };

    await visit("map", W);
    const listBtn = page.getByRole("button", { name: new RegExp(`^${t(lang, "map.view.list")}$`) });
    if (await listBtn.isVisible().catch(() => false)) {
      await listBtn.click();
      await screenChecks(page, "map list");
      await axe(page, info, "map-list", lang);
    }
    await visit("leaderboard", `${W}/leaderboard`);
    await visit("today", `${W}/today`);
    await visit("island", C);

    for (const b of BUILDINGS) {
      await page.goto(C);
      await page.locator(`[data-building="${b.key}"]`).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await screenChecks(page, `${b.key} dialog`);
      await axe(page, info, `${b.key}-dialog`, lang);
      await dialog.getByRole("button", { name: new RegExp(`^${t(lang, "island.dialog.confirm")}$`) }).click();
      await page.waitForURL(b.url, { timeout: 60_000 });
      if (b.ready) await expect(page.getByRole("button", { name: rx(b.ready(lang)) })).toBeVisible({ timeout: 120_000 });
      else await page.waitForTimeout(2500);
      await screenChecks(page, b.key);
      await axe(page, info, b.key, lang);
      await shot(page, info, `sweep-${b.key}-${lang}`);
    }
    assertClean(problems, info);
  });
}
