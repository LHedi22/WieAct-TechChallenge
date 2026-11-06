import { defineConfig, devices } from "@playwright/test";

/**
 * Audit-only E2E suite against the `lw-audit` mock stack (frontend :5174, API :8000).
 * BASE_URL / API_URL override for other profiles. Artifacts go to ../artifacts/e2e.
 */
const desktop = { viewport: { width: 1440, height: 900 } };
const phone = { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true };

export default defineConfig({
  testDir: "./tests",
  outputDir: "../artifacts/e2e/results",
  timeout: 240_000,
  expect: { timeout: 20_000 },
  fullyParallel: true,
  workers: 2,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "../artifacts/e2e/results.json" }]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 20_000,
  },
  projects: [
    { name: "chromium-desktop", use: { ...devices["Desktop Chrome"], ...desktop } },
    { name: "chromium-phone", use: { ...devices["Desktop Chrome"], ...phone } },
    { name: "firefox-desktop", grep: /@main/, use: { ...devices["Desktop Firefox"], ...desktop } },
    { name: "webkit-desktop", grep: /@main/, use: { ...devices["Desktop Safari"], ...desktop } },
  ],
});
