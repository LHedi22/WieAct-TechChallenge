import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";
import { i18nReady, initI18n } from "@/i18n";

initI18n("en", ["fr", "ar", "ar-TN"]);
await i18nReady(); // every locale in the store before a test clones an instance
// findBy*/waitFor: 1 s by default, which a busy host overruns (audit OPT-33)
configure({ asyncUtilTimeout: 3_000 });

afterEach(() => cleanup());
