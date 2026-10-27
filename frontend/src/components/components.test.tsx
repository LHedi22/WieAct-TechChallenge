import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWith } from "@/test/render";
import { Bidi } from "./Bidi";
import { CoinCounter, StreakCounter } from "./Counters";
import { Input } from "./Input";
import { PixelButton } from "./PixelButton";
import { SegmentedProgress } from "./progress";
import { toIntegerScale } from "./sprite/scale";
import { Sprite } from "./sprite/Sprite";

describe("PixelButton", () => {
  it("renders each variant with AA-safe fills", () => {
    renderWith(
      <>
        <PixelButton variant="spend">Spend</PixelButton>
        <PixelButton variant="success">OK</PixelButton>
      </>,
    );
    expect(screen.getByRole("button", { name: "Spend" }).className).toContain("bg-terracotta-ink");
    expect(screen.getByRole("button", { name: "OK" }).className).toContain("bg-olive-ink");
  });

  it("is a real disabled button without the lip", () => {
    renderWith(<PixelButton disabled>Nope</PixelButton>);
    const b = screen.getByRole("button", { name: "Nope" });
    expect(b).toBeDisabled();
    expect(b.className).not.toContain("shadow-lip ");
    expect(b).toHaveAttribute("type", "button");
  });
});

describe("Input", () => {
  it("links the error message and marks the field invalid", () => {
    renderWith(<Input label="Invite code" error="That code doesn't match any world." />);
    const input = screen.getByLabelText("Invite code");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("That code doesn't match any world.");
  });

  it("has no error state by default", () => {
    renderWith(<Input label="Nickname" />);
    expect(screen.getByLabelText("Nickname")).not.toHaveAttribute("aria-invalid");
  });
});

describe("Sprite", () => {
  it("uses a generated placeholder until real art exists, at integer scale", () => {
    renderWith(<Sprite name="coin" scale={3} alt="Coins" />);
    const img = screen.getByRole("img", { name: "Coins" });
    expect(img).toHaveAttribute("data-placeholder", "true");
    expect(img.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(img).toHaveAttribute("width", "48");
    expect(img.className).toContain("pixelated");
  });

  it("is hidden from screen readers when decorative", () => {
    const { container } = renderWith(<Sprite name="water" />);
    expect(container.querySelector("img")).toHaveAttribute("aria-hidden", "true");
  });

  it("never renders fractional scales", () => {
    expect(toIntegerScale(2.5)).toBe(3);
    expect(toIntegerScale(0.3)).toBe(1);
    expect(toIntegerScale(9)).toBe(6);
  });
});

describe("Bidi and counters", () => {
  it("isolates fragments with <bdi>", () => {
    const { container } = renderWith(<Bidi>B2</Bidi>);
    expect(container.querySelector("bdi")).toHaveTextContent("B2");
  });

  it("formats counters with Western digits and plurals in Arabic", () => {
    const { container } = renderWith(
      <>
        <CoinCounter value={20} />
        <StreakCounter days={2} />
      </>,
      { lang: "ar" },
    );
    expect(container).toHaveTextContent("20");
    expect(container).toHaveTextContent("يومان متتاليان");
    expect(container.textContent).not.toMatch(/[٠-٩]/);
  });

  it("uses English plurals", () => {
    const { container } = renderWith(<StreakCounter days={1} />);
    expect(container).toHaveTextContent("1 day streak");
  });
});

describe("SegmentedProgress", () => {
  it("announces the current question", () => {
    renderWith(<SegmentedProgress segments={["correct", "wrong", "current", "pending"]} />);
    expect(screen.getByRole("list", { name: "Question 3 of 4" })).toBeInTheDocument();
    expect(screen.getByText("Q3")).toBeInTheDocument();
  });
});
