import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";
import { initI18n } from "@/i18n";

initI18n("en");
// findBy*/waitFor: 1 s by default, which a busy host overruns (audit OPT-33)
configure({ asyncUtilTimeout: 3_000 });

afterEach(() => cleanup());
