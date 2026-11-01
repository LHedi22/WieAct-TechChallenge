import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "@/i18n";
import type { Language } from "@/i18n/languages";
import { Player } from "./Player";

const SCRIPT = { title: "Limits", segments: ["First idea.", "Second idea.", "Recap."] };

class FakeUtterance {
  voice: unknown = null;
  lang = "";
  rate = 1;
  onend: (() => void) | null = null;
  constructor(public text: string) {}
}

let spoken: FakeUtterance[] = [];
function fakeSpeech(langs: string[]) {
  spoken = [];
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  Object.defineProperty(window, "speechSynthesis", {
    configurable: true,
    value: {
      getVoices: () => langs.map((lang) => ({ lang, name: lang })),
      speak: (u: FakeUtterance) => spoken.push(u),
      cancel: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  });
}

function show(language: string, lang: Language = "en") {
  return render(
    <I18nextProvider i18n={i18n.cloneInstance({ lng: lang })}>
      <Player script={SCRIPT} language={language} />
    </I18nextProvider>,
  );
}

beforeEach(() => fakeSpeech(["en-US", "fr-FR", "ar-SA"]));
afterEach(() => vi.unstubAllGlobals());

describe("Audio player", () => {
  it("reads the segments one by one and highlights the current one", async () => {
    show("en");
    await userEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(spoken.map((u) => u.text)).toEqual(["First idea."]);
    expect(spoken[0]?.lang).toBe("en-US");
    expect(screen.getByRole("button", { name: "First idea." })).toHaveAttribute(
      "aria-current",
      "true",
    );
    spoken[0]?.onend?.();
    expect(await screen.findByRole("button", { name: "Second idea." })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(spoken.map((u) => u.text)).toEqual(["First idea.", "Second idea."]);
  });

  it("changes speed and jumps to a segment", async () => {
    show("en");
    await userEvent.selectOptions(screen.getByLabelText("Speed"), "1.5");
    await userEvent.click(screen.getByRole("button", { name: "Recap." }));
    expect(spoken.at(-1)?.text).toBe("Recap.");
    expect(spoken.at(-1)?.rate).toBe(1.5);
    expect(screen.getByText("Part 3 of 3")).toBeInTheDocument();
  });

  it("is transcript-only in Darija", () => {
    show("ar-TN", "ar-TN");
    expect(screen.getByTestId("transcript-only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "اسمع" })).not.toBeInTheDocument();
    const list = screen.getByRole("list");
    expect(
      within(list)
        .getAllByRole("button")
        .every((b) => b.hasAttribute("disabled")),
    ).toBe(true);
  });

  it("is transcript-only when the browser has no voice for the language", () => {
    fakeSpeech(["en-US"]);
    show("fr", "fr");
    expect(screen.getByTestId("transcript-only")).toHaveTextContent("pas de voix");
  });
});
