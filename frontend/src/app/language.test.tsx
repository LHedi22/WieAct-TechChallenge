import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { LanguageSwitcher } from "@/components";
import { dirFor, numberLocale } from "@/i18n/languages";
import { useDocumentLanguage } from "./useDocumentLanguage";
import { useUiStore } from "./uiStore";

function Harness() {
  useDocumentLanguage();
  return <LanguageSwitcher />;
}

describe("language → <html dir lang>", () => {
  beforeEach(() => useUiStore.setState({ language: "en" }));

  it("maps Arabic and Darija to RTL", () => {
    expect(dirFor("en")).toBe("ltr");
    expect(dirFor("fr")).toBe("ltr");
    expect(dirFor("ar")).toBe("rtl");
    expect(dirFor("ar-TN")).toBe("rtl");
  });

  it("sets dir and lang on <html> when switching", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(document.documentElement.dir).toBe("ltr");

    await user.click(screen.getByRole("button", { name: "العربية" }));
    expect(document.documentElement.dir).toBe("rtl");
    expect(document.documentElement.lang).toBe("ar");
    expect(screen.getByRole("button", { name: "العربية" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "تونسي (Darija)" }));
    expect(document.documentElement.lang).toBe("ar-TN");
    expect(document.documentElement.dir).toBe("rtl");

    await user.click(screen.getByRole("button", { name: "Français" }));
    expect(document.documentElement.dir).toBe("ltr");
    expect(document.documentElement.lang).toBe("fr");
  });

  it("keeps Western digits in Arabic", () => {
    expect(new Intl.NumberFormat(numberLocale("ar")).format(2340)).toMatch(/2.?340/);
  });
});
