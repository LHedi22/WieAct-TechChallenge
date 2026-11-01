import { describe, expect, it } from "vitest";
import { limitConcurrency } from "./util";

describe("limitConcurrency", () => {
  it("runs at most n tasks at once, in order, and passes results and errors through", async () => {
    const run = limitConcurrency(2);
    let active = 0;
    let peak = 0;
    const started: number[] = [];
    const release: (() => void)[] = [];
    const task = (i: number) => () =>
      new Promise<number>((resolve, reject) => {
        active += 1;
        peak = Math.max(peak, active);
        started.push(i);
        release[i] = () => {
          active -= 1;
          if (i === 3) reject(new Error("boom"));
          else resolve(i * 10);
        };
      });
    const tick = () => new Promise((r) => setTimeout(r, 0));

    const settled = Promise.allSettled([0, 1, 2, 3, 4].map((i) => run(task(i))));
    await tick();
    expect(started).toEqual([0, 1]); // the rest wait their turn
    release[1]!();
    await tick();
    expect(started).toEqual([0, 1, 2]);
    release[0]!();
    await tick();
    release[2]!();
    await tick();
    release[3]!();
    await tick();
    release[4]!();
    await expect(settled).resolves.toEqual([
      { status: "fulfilled", value: 0 },
      { status: "fulfilled", value: 10 },
      { status: "fulfilled", value: 20 },
      { status: "rejected", reason: new Error("boom") },
      { status: "fulfilled", value: 40 },
    ]);
    expect(peak).toBe(2); // a failed task frees its slot too (task 4 ran)
  });
});
