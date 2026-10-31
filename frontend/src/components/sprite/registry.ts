import { color } from "@/theme/tokens";
import { artSvg } from "./art";

/**
 * Every sprite the app uses, with its native 1× pixel size. Real art: drop
 * `design/assets/sprites/<name>.png` (1×, same size) and it replaces the placeholder automatically —
 * no code change. Until then a placeholder (coloured blocks with an ink outline) is generated.
 */
type Motif = "block" | "roof" | "band" | "dot" | "columns";

interface SpriteDef {
  w: number;
  h: number;
  fill: string;
  accent: string;
  motif: Motif;
}

const c = color;

export const SPRITES = {
  // icons (16×16)
  lantern: { w: 16, h: 16, fill: c.cat, accent: c.sand.DEFAULT, motif: "dot" },
  lock: { w: 16, h: 16, fill: c.sand.dark, accent: c.ink, motif: "dot" },
  trophy: { w: 16, h: 16, fill: c.cat, accent: c.sand.DEFAULT, motif: "roof" },
  chest: { w: 16, h: 16, fill: c.terracotta.DEFAULT, accent: c.cat, motif: "band" },
  coin: { w: 16, h: 16, fill: c.terracotta.DEFAULT, accent: c.terracotta.light, motif: "dot" },
  star: { w: 16, h: 16, fill: c.primary.DEFAULT, accent: c.primary.light, motif: "dot" },
  flame: { w: 16, h: 16, fill: c.terracotta.DEFAULT, accent: c.cat, motif: "roof" },
  hourglass: { w: 16, h: 16, fill: c.sand.DEFAULT, accent: c.terracotta.DEFAULT, motif: "band" },
  // world pieces (16×16)
  water: { w: 16, h: 16, fill: c.sea.DEFAULT, accent: c.sea.foam, motif: "band" },
  tileBorder: { w: 16, h: 16, fill: c.whitewash, accent: c.primary.DEFAULT, motif: "dot" },
  blueDoor: { w: 16, h: 16, fill: c.primary.DEFAULT, accent: c.primary.dark, motif: "columns" },
  bougainvillea: { w: 16, h: 16, fill: c.bougainvillea, accent: c.olive.DEFAULT, motif: "dot" },
  oliveBranch: { w: 16, h: 16, fill: c.olive.light, accent: c.olive.DEFAULT, motif: "band" },
  jasmine: { w: 16, h: 16, fill: c.whitewash, accent: c.olive.DEFAULT, motif: "dot" },
  // avatars (16×16)
  avatar1: { w: 16, h: 16, fill: c.sand.DEFAULT, accent: c.primary.DEFAULT, motif: "band" },
  avatar2: { w: 16, h: 16, fill: c.sand.DEFAULT, accent: c.olive.DEFAULT, motif: "band" },
  avatar3: { w: 16, h: 16, fill: c.sand.DEFAULT, accent: c.terracotta.DEFAULT, motif: "band" },
  avatar4: { w: 16, h: 16, fill: c.sand.DEFAULT, accent: c.sea.DEFAULT, motif: "band" },
  avatar5: { w: 16, h: 16, fill: c.sand.DEFAULT, accent: c.bougainvillea, motif: "band" },
  avatar6: { w: 16, h: 16, fill: c.sand.DEFAULT, accent: c.island[4]!, motif: "band" },
  // map pieces
  island: { w: 48, h: 32, fill: c.olive.light, accent: c.sand.DEFAULT, motif: "band" },
  islandLocked: { w: 48, h: 32, fill: c.sand.dark, accent: c.whitewash, motif: "band" },
  boat: { w: 16, h: 16, fill: c.whitewash, accent: c.terracotta.DEFAULT, motif: "roof" },
  // buildings (32×32)
  quizHall: { w: 32, h: 32, fill: c.sand.dark, accent: c.terracotta.DEFAULT, motif: "columns" },
  tutorCafe: { w: 32, h: 32, fill: c.whitewash, accent: c.primary.DEFAULT, motif: "roof" },
  studyStudio: { w: 32, h: 32, fill: c.whitewash, accent: c.sea.DEFAULT, motif: "roof" },
  audioStudio: { w: 32, h: 32, fill: c.whitewash, accent: c.terracotta.DEFAULT, motif: "roof" },
  teachBackArena: { w: 32, h: 32, fill: c.sand.DEFAULT, accent: c.whitewash, motif: "columns" },
  // mascot (24×24)
  catWaving: { w: 24, h: 24, fill: c.cat, accent: c.primary.DEFAULT, motif: "band" },
  catReading: { w: 24, h: 24, fill: c.cat, accent: c.sand.DEFAULT, motif: "block" },
  catThinking: { w: 24, h: 24, fill: c.cat, accent: c.primary.DEFAULT, motif: "dot" },
  catCelebrating: { w: 24, h: 24, fill: c.cat, accent: c.sea.DEFAULT, motif: "roof" },
} satisfies Record<string, SpriteDef>;

export type SpriteName = keyof typeof SPRITES;

const realArt = import.meta.glob<string>("../../../../design/assets/sprites/*.png", {
  eager: true,
  query: "?url",
  import: "default",
});

function realSrc(name: SpriteName): string | undefined {
  const entry = Object.entries(realArt).find(([path]) => path.endsWith(`/${name}.png`));
  return entry?.[1];
}

function motifRects({ w, h, motif }: SpriteDef): [number, number, number, number][] {
  const third = Math.floor(h / 3);
  const mid = Math.floor(w / 2);
  switch (motif) {
    case "roof":
      return [[1, 1, w - 2, third]];
    case "band":
      return [[1, Math.floor(h / 2), w - 2, Math.max(2, Math.floor(h / 6))]];
    case "dot":
      return [
        [
          mid - Math.floor(w / 6),
          Math.floor(h / 2) - Math.floor(h / 6),
          Math.floor(w / 3),
          Math.floor(h / 3),
        ],
      ];
    case "columns":
      return [3, mid - 1, w - 5].map(
        (x) => [x, third, 2, h - third - 1] as [number, number, number, number],
      );
    case "block":
      return [[2, h - third - 1, w - 4, third]];
  }
}

function placeholder(name: SpriteName, def: SpriteDef): string {
  const art = artSvg(name, def.w, def.h);
  if (art) {
    return `data:image/svg+xml,${encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" width="${def.w}" height="${def.h}" shape-rendering="crispEdges">${art}</svg>`,
    )}`;
  }
  const rects = motifRects(def)
    .map(
      ([x, y, rw, rh]) =>
        `<rect x="${x}" y="${y}" width="${rw}" height="${rh}" fill="${def.accent}"/>`,
    )
    .join("");
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${def.w}" height="${def.h}" shape-rendering="crispEdges">` +
    `<rect x="0.5" y="0.5" width="${def.w - 1}" height="${def.h - 1}" fill="${def.fill}" stroke="${color.ink}"/>` +
    rects +
    `</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

export function spriteSource(name: SpriteName): { src: string; placeholder: boolean } {
  const real = realSrc(name);
  return real
    ? { src: real, placeholder: false }
    : { src: placeholder(name, SPRITES[name]), placeholder: true };
}
