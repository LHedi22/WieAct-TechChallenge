import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWith } from "@/test/render";
import { TestDataChip } from "./TestDataChip";

describe("TestDataChip (audit F-OFF-1)", () => {
  it("labels content written by a test model", () => {
    renderWith(<TestDataChip madeBy="mock" />);
    expect(screen.getByText("Test data (mock)")).toBeInTheDocument();
  });

  it("shows nothing for platform content or when unknown", () => {
    const { container } = renderWith(
      <>
        <TestDataChip madeBy="cloud" />
        <TestDataChip madeBy={null} />
        <TestDataChip />
      </>,
    );
    expect(container.textContent).toBe("");
  });
});
