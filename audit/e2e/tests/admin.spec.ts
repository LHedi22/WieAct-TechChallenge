import { expect, test } from "@playwright/test";

/**
 * Admin smoke (8 Nov): sign in → flip Quick mode → grant coins → see the admin log row.
 * Needs a stack with ADMIN_TOKEN set (mock provider only). The token comes from the environment
 * (ADMIN_TOKEN) and is never printed; run with
 *   BASE_URL=http://127.0.0.1:5174 API_URL=http://127.0.0.1:8001 ADMIN_TOKEN=… \
 *     npx playwright test tests/admin.spec.ts --workers=1
 * One worker: the Quick-mode switch is global, so two projects in parallel would race on it.
 */
const API = process.env.API_URL ?? "http://localhost:8000";
const TOKEN = process.env.ADMIN_TOKEN ?? "";

test.skip(!TOKEN, "ADMIN_TOKEN is not set for this run");

test("admin: sign in, force Quick mode, grant coins, see the log @admin", async ({ page, request }) => {
  const nickname = `adm_${Date.now().toString(36)}`;
  const signup = await request.post(`${API}/api/auth/signup`, {
    data: { nickname, password: "smoke-test-pass-1", ui_language: "ar" },
  });
  expect(signup.status()).toBe(201);

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Learning World admin" })).toBeVisible();
  // the admin side is English and left-to-right even for an Arabic-speaking student's browser
  await expect(page.locator("[dir=ltr][lang=en]").filter({ visible: true }).first()).toBeVisible();
  await page.getByLabel("Admin token").fill(TOKEN);
  await page.getByLabel(/Your name/).fill("smoke");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Switches" })).toBeVisible();
  // the token is gone from the page and never stored in the browser
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  expect(await page.content()).not.toContain(TOKEN);

  // Quick mode on for 5 minutes, then off again
  const quick = page.locator("section", { has: page.getByRole("heading", { name: "Force Quick mode" }) });
  await quick.getByLabel("For").selectOption("5");
  await quick.getByRole("button", { name: "Turn on" }).click();
  await expect(quick.getByText(/^On/)).toBeVisible();
  await expect(quick.getByText(/Changed by smoke/)).toBeVisible();
  const status = await (await request.get(`${API}/api/system/status`)).json();
  expect(status.quick_mode_forced).toBe(true);
  await quick.getByRole("button", { name: "Turn off" }).click();
  await expect(quick.getByText("Off", { exact: true })).toBeVisible();

  // grant 7 earned coins to the new student
  await page.getByRole("link", { name: "Users" }).click();
  await page.getByLabel("Nickname").fill(nickname);
  await page.getByRole("button", { name: "Search" }).click();
  await page.getByRole("button", { name: "Open" }).filter({ visible: true }).first().click();
  await expect(page.getByRole("heading", { name: nickname })).toBeVisible();
  await page.getByText("Grant or remove coins").click();
  const coins = page.locator("details", { hasText: "Grant or remove coins" });
  await coins.getByLabel("Coins (negative removes)").fill("7");
  await coins.getByLabel("Reason (required)").fill("smoke test grant");
  await coins.getByRole("button", { name: "Grant 7 coins" }).click();
  await expect(coins.getByText("Done: written to the ledger.")).toBeVisible();
  await expect(page.getByText(/27 coins/).filter({ visible: true }).first()).toBeVisible(); // 20 free today + 7 earned

  // the admin log has the row, with the reason
  await page.getByRole("link", { name: "Admin log" }).click();
  await page.getByLabel("Action").fill("coins.adjust");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText("smoke test grant").filter({ visible: true }).first()).toBeVisible();
  await expect(page.getByText("coins.adjust").filter({ visible: true }).first()).toBeVisible();
});
