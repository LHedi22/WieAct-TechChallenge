import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWith } from "@/test/render";
import { StyleguidePage } from "./StyleguidePage";

describe("/styleguide", () => {
  it("renders every section in English", () => {
    renderWith(<StyleguidePage />);
    for (const name of [
      "Colors",
      "Type",
      "Buttons",
      "Cards, banners and chips",
      "Counters and progress",
      "Loading stages",
      "World pieces",
      "The five buildings · same on every island",
      "Mascot · the Sidi Bou Said cat",
    ]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("status")).toHaveLength(4);
  });

  it("renders in Arabic", () => {
    renderWith(<StyleguidePage />, { lang: "ar" });
    expect(screen.getByRole("heading", { name: "الألوان" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "إنفاق / مكافأة" })).toBeInTheDocument();
  });

  it("shows English and Arabic side by side with their own dir", () => {
    const { container } = renderWith(<StyleguidePage />, { route: "/styleguide?compare=1" });
    const en = container.querySelector('[data-column="en"][lang="en"][dir="ltr"]');
    const ar = container.querySelector('[data-column="ar"][lang="ar"][dir="rtl"]');
    expect(en).not.toBeNull();
    expect(ar).not.toBeNull();
    expect(ar).toHaveTextContent("الألوان");
    expect(en).toHaveTextContent("Colors");
  });
});
