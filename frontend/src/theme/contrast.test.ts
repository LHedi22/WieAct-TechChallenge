// Audit OPT-24 (F-A11Y-1): chip text on a translucent tint failed WCAG AA (axe: 181 nodes on 14
// screens, ≈ 3.4:1). Every tinted text pair must reach 4.5:1 on each page background.
import { describe, expect, it } from "vitest";
import { color } from "./tokens";

type RGB = [number, number, number];

function rgb(hex: string): RGB {
  const h = hex.replace("#", "");
  const at = (i: number) => parseInt(h.slice(i, i + 2), 16) / 255;
  return [at(0), at(2), at(4)];
}

function luminance([r, g, b]: RGB): number {
  const f = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function ratio(fg: RGB, bg: RGB): number {
  const a = luminance(fg);
  const b = luminance(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function over(tint: string, alpha: number, base: RGB): RGB {
  const t = rgb(tint);
  const mix = (i: 0 | 1 | 2) => t[i] * alpha + base[i] * (1 - alpha);
  return [mix(0), mix(1), mix(2)];
}

// text, tint, alpha: Chip (cost, weakSpot, confidence) and the admin notices
const PAIRS: [string, string, string, number][] = [
  ["olive ink on olive-light/30", color.olive.ink, color.olive.light, 0.3],
  ["terracotta ink on terracotta-light/25", color.terracotta.ink, color.terracotta.light, 0.25],
  ["terracotta ink on terracotta-light/30", color.terracotta.ink, color.terracotta.light, 0.3],
];
const WHITE: RGB = [1, 1, 1];
const BASES: Record<string, RGB> = {
  sand: rgb(color.sand.DEFAULT),
  whitewash: rgb(color.whitewash),
  white: WHITE,
};

describe("tinted text contrast", () => {
  for (const [name, fg, tint, alpha] of PAIRS) {
    for (const [base, bg] of Object.entries(BASES)) {
      it(`${name} on ${base} reaches 4.5:1`, () => {
        expect(ratio(rgb(fg), over(tint, alpha, bg))).toBeGreaterThanOrEqual(4.5);
      });
    }
  }
});
