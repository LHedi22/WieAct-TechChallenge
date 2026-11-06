import { expect, test } from "@playwright/test";
import { LANGS, type Lang, assertClean, guard, nick, rx, screenChecks, setLanguage, shot, stem, t } from "./lib";

/**
 * @main  Landing → sign up → onboarding → join OLIVE-7Q2 → placement → island → Quiz Hall
 * (wrong → hint → second try, skip, results) → back to the island. Through the UI only.
 * Measures landing → first quiz question (target < 5 min at human speed; this is scripted speed).
 */
for (const lang of LANGS) {
  test(`@main first journey ${lang}`, async ({ page }, info) => {
    const problems = guard(page, [/401 .*\/api\/auth\/(session|me)/]);
    await setLanguage(page, lang);
    const t0 = Date.now();

    // Landing
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(stem(lang, "landing.title").slice(0, 12));
    await screenChecks(page, "landing");
    await shot(page, info, `01-landing-${lang}`);
    await page.getByRole("link", { name: rx(t(lang, "landing.start")) }).or(page.getByRole("button", { name: rx(t(lang, "landing.start")) })).first().click();

    // Sign up
    await page.getByLabel(t(lang, "auth.nickname"), { exact: false }).first().fill(nick("ui"));
    await page.getByLabel(t(lang, "auth.password"), { exact: false }).first().fill("audit-pass-123");
    await page.getByRole("button", { name: rx(t(lang, "auth.signup.submit")) }).click();
    await page.waitForURL(/\/welcome/);

    // Onboarding: walk the steps (style questions are radio cards; then Continue / Set sail)
    const cont = page.getByRole("button", { name: new RegExp(`^(${t(lang, "onboarding.continue")}|${t(lang, "onboarding.setSail")})$`) });
    for (let i = 0; i < 25 && /\/welcome/.test(page.url()); i++) {
      const radios = page.getByRole("radio");
      if ((await radios.count()) > 0 && (await radios.first().isVisible())) {
        await radios.first().check({ force: true }).catch(() => radios.first().click({ force: true }));
      }
      if (await cont.first().isVisible().catch(() => false)) {
        if (await cont.first().isEnabled()) await cont.first().click();
      }
      await page.waitForTimeout(250);
      if (i === 8) await screenChecks(page, "onboarding mid");
    }
    expect(page.url(), "left onboarding").not.toMatch(/\/welcome/);

    // Join the demo world by code (lower case + space: accepted formats)
    await page.waitForURL(/\/worlds\//);
    if (/\/worlds\/new/.test(page.url())) {
      await page.getByLabel(t(lang, "worlds.join.label")).fill("olive 7q2");
      await page.getByRole("button", { name: new RegExp(`^${t(lang, "worlds.join.submit")}$`) }).click();
    }
    await page.waitForURL(/\/worlds\/[0-9a-f-]{36}$/, { timeout: 60_000 });
    await screenChecks(page, "map");
    await shot(page, info, `02-map-${lang}`);

    // Placement for the first island that asks for it
    // Map view (desktop) labels the island button; list view (phones) shows "Start 3-minute quiz"
    await page
      .getByRole("button", { name: rx(stem(lang, "map.island.startPlacementFor")) })
      .or(page.getByRole("button", { name: rx(t(lang, "map.island.startPlacement")) }))
      .first()
      .click();
    await page.waitForURL(/placement/);
    for (let i = 0; i < 12; i++) {
      const opts = page.getByRole("radio");
      await opts.first().waitFor({ state: "attached", timeout: 120_000 });
      await opts.first().check({ force: true });
      const finish = page.getByRole("button", { name: rx(t(lang, "placement.finish")) });
      if (await finish.isVisible().catch(() => false)) {
        await finish.click();
        break;
      }
      await page.getByRole("button", { name: rx(t(lang, "placement.next")) }).click();
    }
    await expect(page.getByText(t(lang, "placement.result.title"))).toBeVisible({ timeout: 60_000 });
    await screenChecks(page, "placement result");
    await page.getByRole("link", { name: rx(t(lang, "placement.result.toIsland")) }).or(page.getByRole("button", { name: rx(t(lang, "placement.result.toIsland")) })).first().click();

    // Island → Quiz Hall
    await page.waitForURL(/\/courses\/[0-9a-f-]{36}$/);
    await screenChecks(page, "island");
    await shot(page, info, `03-island-${lang}`);
    await page.locator('[data-building="quiz_hall"]').click();
    await page.getByRole("button", { name: new RegExp(`^${t(lang, "island.dialog.confirm")}$`) }).click();
    await page.waitForURL(/\/quiz\//);
    await expect(page.getByRole("button", { name: rx(t(lang, "quiz.check")) })).toBeVisible({ timeout: 120_000 });
    const firstQuestionMs = Date.now() - t0;
    info.annotations.push({ type: "landing→first quiz question (scripted)", description: `${firstQuestionMs} ms` });
    await screenChecks(page, "quiz question");
    await shot(page, info, `04-quiz-${lang}`);

    // Q1: pick the last option (often wrong on the mock) → Check → maybe hint + second try
    const retry = page.getByRole("button", { name: rx(stem(lang, "quiz.tryAgain")) });
    const next = page.getByRole("button", { name: rx(t(lang, "quiz.next")) });
    const results = page.getByRole("button", { name: rx(t(lang, "quiz.seeResults")) });
    const skip = page.getByRole("button", { name: rx(t(lang, "quiz.skip")) });
    /** Wait until one of the locators is visible; returns its index. */
    const which = async (...ls: import("@playwright/test").Locator[]) =>
      Promise.any(ls.map((l, i) => l.waitFor({ state: "visible", timeout: 30_000 }).then(() => i)));
    let sawHint = false;
    let skipped = false;
    for (let q = 0; q < 12; q++) {
      const options = page.locator("main li button:not([disabled])");
      if (q === 3 && !skipped) {
        await skip.click(); // skip one question: answer + explanation shown, no points
        skipped = true;
      } else {
        await options.last().click();
        await page.getByRole("button", { name: rx(t(lang, "quiz.check")) }).click();
        if ((await which(retry, next, results)) === 0) {
          await expect(page.getByText(t(lang, "quiz.notQuite"))).toBeVisible();
          sawHint = true;
          await options.first().click();
          await retry.click();
        }
      }
      if ((await which(next, results)) === 1) {
        await results.click();
        break;
      }
      await next.click();
    }
    expect(sawHint, "saw at least one hint + second try").toBe(true);
    await expect(page.getByText(t(lang, "quiz.results.score"))).toBeVisible({ timeout: 60_000 });
    await screenChecks(page, "quiz results");
    await shot(page, info, `05-results-${lang}`);
    assertClean(problems, info);
  });
}
