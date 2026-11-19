// Audit OPT-21: one 943 kB entry chunk held every screen. The five buildings, placement and the
// styleguide are their own chunks now, loaded when a student opens them; so are the locales.
import { describe, expect, it } from "vitest";
import i18nSource from "../i18n/index.ts?raw";
import app from "./App.tsx?raw";
const LAZY = [
  "features/quiz/QuizStartPage",
  "features/quiz/QuizAttemptPage",
  "features/tutor/TutorPage",
  "features/arena/ArenaPage",
  "features/studio/StudioPage",
  "features/audio/AudioPage",
  "features/placement/PlacementPage",
  "features/styleguide/StyleguidePage",
  "features/admin/AdminApp",
];

describe("route code splitting", () => {
  for (const path of LAZY) {
    it(`${path} is loaded on demand`, () => {
      expect(app).not.toMatch(new RegExp(`^import .* from "@/${path}";$`, "m"));
      expect(app).toContain(`import("@/${path}")`);
    });
  }
});

describe("locale code splitting", () => {
  it("bundles English only; the other locales load when chosen", () => {
    expect(i18nSource).toMatch(/^import en from "\.\/en\.json";$/m);
    for (const lang of ["fr", "ar", "ar-TN"]) {
      expect(i18nSource).not.toMatch(new RegExp(`^import .* from "\\./${lang}\\.json";$`, "m"));
      expect(i18nSource).toContain(`"./${lang}.json"`);
    }
  });
});
