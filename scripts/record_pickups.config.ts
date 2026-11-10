import { defineConfig } from "@playwright/test";

/** Pickup clips (scripts/record_pickups.ts); run from scripts/video so node_modules resolves. */
export default defineConfig({
  testDir: ".",
  testMatch: /record_pickups\.ts$/,
  outputDir: "../docs/video/pickups/_pw",
  timeout: 45 * 60_000,
  workers: 1,
  reporter: [["list"]],
  use: { actionTimeout: 30_000 },
});
