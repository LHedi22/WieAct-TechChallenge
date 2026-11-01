import type { Config } from "tailwindcss";
// Single source of truth for the theme (docs/DESIGN.md). In Docker, ../design is mounted at /design.
import tokens from "../design/tokens.json";

const { color, font, fontSize, radius, shadow, motion } = tokens;

type FontSize = [string, { lineHeight?: string; fontWeight?: string }];

const island = Object.fromEntries(color.island.map((hex, i) => [String(i + 1), hex]));

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        whitewash: color.whitewash,
        sand: color.sand,
        ink: color.ink,
        primary: color.primary,
        sea: color.sea,
        terracotta: color.terracotta,
        olive: color.olive,
        danger: color.danger,
        cat: color.cat,
        bougainvillea: color.bougainvillea,
        island,
      },
      fontFamily: { heading: font.heading, body: font.body },
      fontSize: fontSize as unknown as Record<string, FontSize>,
      borderRadius: { soft: radius.soft, "pixel-step": radius.pixelStep },
      boxShadow: { lip: shadow.lip, "lip-pressed": shadow.lipPressed, panel: shadow.panel },
      transitionDuration: { press: `${motion.pressMs}ms`, sail: `${motion.sailMs}ms` },
      keyframes: {
        water: { from: { backgroundPosition: "0 0" }, to: { backgroundPosition: "128px 64px" } },
      },
      animation: { water: `water ${motion.waterTileMs}ms linear infinite` },
    },
  },
  plugins: [],
} satisfies Config;
