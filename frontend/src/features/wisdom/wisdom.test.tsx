import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { WisdomTip } from "@/api/client";
import { renderWith } from "@/test/render";
import { WisdomTipBody } from "./WisdomTip";

const tip = (n: number, trap: string): WisdomTip => ({
  id: `00000000-0000-0000-0000-00000000000${n}`,
  course_id: "c1",
  concept: "limits",
  mistake_type: "misconception",
  language: "en",
  trap,
  why: "That skips the condition.",
  right: "Check the condition first.",
  student_count: 3,
});

describe("WisdomTipBody", () => {
  it("shows the anonymous pattern and cycles with 'Show me another tip'", async () => {
    renderWith(<WisdomTipBody tips={[tip(1, "First trap."), tip(2, "Second trap.")]} />);
    expect(screen.getByText(/3 classmates fell for this/)).toBeInTheDocument();
    expect(screen.getByText("First trap.")).toBeInTheDocument();
    expect(screen.getByText("Names are hidden. Only the pattern is shared.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Show me another tip/ }));
    expect(screen.getByText("Second trap.")).toBeInTheDocument();
  });

  it("has no 'another tip' button for a single tip, and reads in Arabic", () => {
    renderWith(<WisdomTipBody tips={[tip(1, "فخ.")]} />, { lang: "ar" });
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/زملاء وقعوا في هذا الفخ/)).toBeInTheDocument();
    expect(screen.getByText("الأسماء مخفية. نشارك النمط فقط.")).toBeInTheDocument();
  });
});

describe("Loading-screen tips", () => {
  it("shows only this course's tips, else a general study tip", async () => {
    const { useWisdomTip } = await import("./useWisdomTip");
    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
    const { LoadingStages } = await import("@/components");
    const other = { ...tip(1, "Other course trap."), course_id: "c2" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ tips: [other] }), { status: 200 })),
    );
    function Screen({ course }: { course: string }) {
      return <LoadingStages stages={[]} tip={useWisdomTip("w1", course)} />;
    }
    const qc = new QueryClient();
    renderWith(
      <QueryClientProvider client={qc}>
        <Screen course="c1" />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("general-tip")).toBeInTheDocument();
    expect(screen.getByText("Study tip")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Other course trap.")).toBeNull();
    vi.unstubAllGlobals();
  });
});
