import { defineConfig } from "@playwright/test";

/**
 * Demo-video recorder (not a test suite). One "test" per shot in record.ts; each writes its own
 * clip to docs/report/video/raw/NN-name.webm. Run one shot at a time:
 *   cd scripts/video && npx playwright test -c playwright.config.ts -g "01-landing"
 * node_modules is a junction to audit/e2e/node_modules (@playwright/test 1.56.1).
 */
export default defineConfig({
  testDir: ".",
  testMatch: /record\.ts$/,
  outputDir: "../../docs/report/video/raw/_pw",
  timeout: 90 * 60_000,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { actionTimeout: 30_000 },
});
