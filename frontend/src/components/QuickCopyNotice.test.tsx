import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWith } from "@/test/render";
import { QuickCopyNotice } from "./QuickCopyNotice";

describe("QuickCopyNotice (audit F-QUICK-1)", () => {
  it("labels a Quick-mode copy and offers the free full version", async () => {
    const onUpgrade = vi.fn();
    renderWith(<QuickCopyNotice onUpgrade={onUpgrade} />);
    expect(screen.getByText("Quick mode")).toBeInTheDocument();
    expect(screen.getByText(/faster model/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Make the full version · Free" }));
    expect(onUpgrade).toHaveBeenCalledOnce();
  });

  it("disables the button while the request is on its way", () => {
    renderWith(<QuickCopyNotice busy onUpgrade={() => {}} />);
    expect(screen.getByRole("button", { name: /full version/ })).toBeDisabled();
  });
});
