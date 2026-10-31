import { color } from "@/theme/tokens";

/** Hand-drawn pixel art for the sprites people see most (map, top bar), drawn from tokens until
 * real PNGs land in design/assets/sprites/. Each piece is a function (x, y) → colour | null on the
 * sprite's own 1× grid; rows are merged into runs so the SVG stays small. */
type Paint = (x: number, y: number) => string | null | undefined;

const c = color;

function svgRects(w: number, h: number, paint: Paint): string {
  let out = "";
  for (let y = 0; y < h; y++) {
    let x = 0;
    while (x < w) {
      const fill = paint(x, y);
      let end = x + 1;
      while (end < w && paint(end, y) === fill) end++;
      if (fill) out += `<rect x="${x}" y="${y}" width="${end - x}" height="1" fill="${fill}"/>`;
      x = end;
    }
  }
  return out;
}

/** Ink outline around a shape: inside pixels with an outside neighbour. */
function outlined(inside: (x: number, y: number) => boolean, fill: Paint): Paint {
  return (x, y) => {
    if (!inside(x, y)) return null;
    const edge = [
      [1, 0],
      [-1, 0],
      [0, 1],
      [0, -1],
    ].some(([dx, dy]) => !inside(x + dx!, y + dy!));
    return edge ? c.ink : fill(x, y);
  };
}

const dist = (x: number, y: number, cx: number, cy: number) =>
  Math.hypot(x + 0.5 - cx, y + 0.5 - cy);

function starInside(x: number, y: number): boolean {
  const px = x + 0.5 - 8;
  const py = y + 0.5 - 8.5;
  const pts = Array.from({ length: 10 }, (_, i) => {
    const r = i % 2 ? 3.3 : 7.8;
    const a = -Math.PI / 2 + (i * Math.PI) / 5;
    return [r * Math.cos(a), r * Math.sin(a)] as const;
  });
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i]!;
    const [xj, yj] = pts[j]!;
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

const flameInside = (s: number) => (x: number, y: number) => {
  const dx = Math.abs(x + 0.5 - 8);
  const body = (dx / (5 * s)) ** 2 + ((y + 0.5 - 10.5) / (4.5 * s)) ** 2 < 1;
  const tip = y >= 15 - 13 * s && y < 10.5 && dx < (y + 0.5 - (15 - 13 * s)) * 0.55;
  return body || tip;
};

// Islands: a wobbly oval in rings (shallows, sand, grass) with trees, two houses and a flag.
function islandPaint(x: number, y: number): string | null {
  const nx = (x + 0.5 - 24) / 23;
  const ny = (y + 0.5 - 16) / 15;
  const d = nx * nx + ny * ny + 0.07 * Math.sin(x * 0.9) + 0.06 * Math.cos(y * 1.3 + x * 0.3);
  if (d >= 1) return null;
  if (d >= 0.78) return (x + y) % 5 === 0 ? c.sea.foam : c.sea.light;
  if (d >= 0.56) return d >= 0.7 && (x * 3 + y) % 7 === 0 ? c.whitewash : c.sand.DEFAULT;
  if (d >= 0.5) return c.sand.dark;
  // trees (2×2 crown + trunk)
  for (const [tx, ty] of [
    [14, 11],
    [18, 15],
    [31, 10],
    [33, 17],
    [12, 17],
  ] as const) {
    if (x >= tx && x <= tx + 1 && y >= ty && y <= ty + 1) return c.olive.DEFAULT;
    if (x === tx && y === ty + 2) return c.terracotta.ink;
  }
  // houses: whitewash walls, blue door, blue dome
  for (const [hx, hy] of [
    [22, 12],
    [26, 17],
  ] as const) {
    if (y === hy && x === hx + 1) return c.primary.DEFAULT;
    if (x >= hx && x <= hx + 2 && y >= hy + 1 && y <= hy + 3)
      return x === hx + 1 && y === hy + 3 ? c.primary.dark : c.whitewash;
  }
  // flag
  if (x === 29 && y >= 9 && y <= 14) return c.ink;
  if (x >= 30 && x <= 32 && y >= 9 && y <= 10) return c.terracotta.DEFAULT;
  return (x * 7 + y * 3) % 11 === 0 ? c.olive.DEFAULT : c.olive.light;
}

function boatPaint(x: number, y: number): string | null {
  // hull
  if (y >= 11 && y <= 13) {
    const inset = y - 11;
    if (x >= 2 + inset && x <= 13 - inset)
      return y === 11 || x === 2 + inset || x === 13 - inset || y === 13
        ? c.ink
        : c.terracotta.DEFAULT;
  }
  if (x === 7 && y >= 2 && y <= 10) return c.ink; // mast
  if (y >= 3 && y <= 9 && x >= 8 && x <= 8 + Math.floor((y - 2) * 0.8)) {
    const right = 8 + Math.floor((y - 2) * 0.8);
    return x === right || y === 9 ? c.ink : c.whitewash;
  }
  if (y === 2 && x >= 8 && x <= 9) return c.primary.DEFAULT; // pennant
  return null;
}

// Buildings (32×32): boxes drawn in order, each with a 1px ink outline; later boxes paint over.
type Box = [number, number, number, number, string, boolean?]; // x, y, w, h, fill, no outline

function boxes(list: Box[]): Paint {
  const layers: [number, number, number, number, string][] = [];
  for (const [x, y, w, h, fill, bare] of list) {
    if (!bare) layers.push([x - 1, y - 1, w + 2, h + 2, c.ink]);
    layers.push([x, y, w, h, fill]);
  }
  return (px, py) => {
    for (let i = layers.length - 1; i >= 0; i--) {
      const [x, y, w, h, fill] = layers[i]!;
      if (px >= x && px < x + w && py >= y && py < y + h) return fill;
    }
    return null;
  };
}

const arches = (y: number, fill: string): Box[] =>
  [5, 9, 13, 17, 21, 25].map((x) => [x, y, 2, 3, fill, true] as Box);

const quizHall = boxes([
  [3, 26, 26, 3, c.sand.dark],
  [4, 10, 24, 16, c.sand.DEFAULT],
  [6, 8, 20, 2, c.sand.dark],
  ...arches(12, c.terracotta.ink),
  ...arches(19, c.terracotta.ink),
  [4, 17, 24, 1, c.sand.dark, true],
  [6, 2, 1, 6, c.ink, true],
  [7, 2, 4, 3, c.terracotta.DEFAULT, true],
]);

const tutorCafe = boxes([
  [6, 12, 20, 16, c.whitewash],
  [14, 20, 4, 8, c.primary.DEFAULT],
  [16, 23, 1, 1, c.sand.DEFAULT, true],
  [8, 15, 3, 3, c.primary.light],
  [21, 15, 3, 3, c.primary.light],
  [4, 10, 24, 2, c.primary.DEFAULT],
  ...[5, 9, 13, 17, 21, 25].map((x) => [x, 10, 2, 2, c.whitewash, true] as Box),
  [3, 6, 4, 4, c.bougainvillea],
  [26, 22, 3, 1, c.terracotta.ink, true],
  [27, 23, 1, 5, c.terracotta.ink, true],
]);

const studyStudio = boxes([
  [6, 14, 20, 14, c.whitewash],
  [10, 10, 12, 4, c.whitewash],
  [12, 7, 8, 3, c.whitewash],
  [14, 6, 4, 1, c.whitewash, true],
  [15, 3, 2, 3, c.primary.DEFAULT, true],
  [14, 21, 4, 7, c.primary.DEFAULT],
  [9, 17, 2, 3, c.primary.DEFAULT],
  [21, 17, 2, 3, c.primary.DEFAULT],
  [6, 14, 20, 1, c.sand.DEFAULT, true],
]);

const audioStudio = boxes([
  [7, 15, 18, 13, c.whitewash],
  [9, 13, 14, 2, c.terracotta.DEFAULT],
  [11, 11, 10, 2, c.terracotta.DEFAULT],
  [13, 9, 6, 2, c.terracotta.DEFAULT],
  [15, 7, 2, 2, c.terracotta.DEFAULT],
  [10, 21, 3, 7, c.primary.DEFAULT],
  [17, 18, 4, 3, c.sea.ink],
  // the music sign: a note on a post
  [27, 11, 1, 7, c.ink, true],
  [25, 17, 3, 2, c.ink, true],
  [28, 11, 2, 2, c.ink, true],
]);

const teachBackArena = boxes([
  [3, 26, 26, 3, c.sand.dark],
  [5, 24, 22, 2, c.sand.DEFAULT],
  [4, 8, 24, 3, c.sand.DEFAULT],
  [8, 6, 16, 2, c.sand.DEFAULT],
  [12, 4, 8, 2, c.sand.DEFAULT],
  ...[6, 12, 18, 24].map((x) => [x, 12, 2, 11, c.whitewash] as Box),
  [4, 11, 24, 1, c.sand.dark, true],
]);

export const ART: Record<string, Paint> = {
  coin: outlined(
    (x, y) => dist(x, y, 8, 8) < 7.2,
    (x, y) =>
      dist(x, y, 8, 8) > 5.4
        ? c.terracotta.DEFAULT
        : x >= 7 && x <= 8 && y >= 5 && y <= 10
          ? c.terracotta.ink
          : x + y < 14
            ? c.terracotta.light
            : c.terracotta.DEFAULT,
  ),
  star: outlined(starInside, (_x, y) => (y < 8 ? c.primary.light : c.primary.DEFAULT)),
  flame: outlined(flameInside(1), (x, y) =>
    flameInside(0.55)(x, y + 2)
      ? c.sand.DEFAULT
      : flameInside(0.8)(x, y + 1)
        ? c.cat
        : c.terracotta.DEFAULT,
  ),
  hourglass: (x, y) => {
    if ((y === 1 || y === 14) && x >= 3 && x <= 12) return c.terracotta.ink;
    if (y < 2 || y > 13) return null;
    const hw = Math.abs(y + 0.5 - 8) * 0.75 + 0.8;
    const dx = Math.abs(x + 0.5 - 8);
    if (dx > hw + 1) return null;
    if (dx > hw) return c.ink;
    if ((y >= 10 && y <= 12) || (y >= 3 && y <= 4) || (y >= 8 && x >= 7 && x <= 8)) return c.cat;
    return c.sea.foam;
  },
  lock: (x, y) => {
    const shackle = y >= 1 && y <= 7 && x >= 4 && x <= 11;
    const hole = y >= 3 && x >= 6 && x <= 9;
    if (shackle && !hole && y < 7) return c.ink;
    if (y >= 7 && y <= 14 && x >= 3 && x <= 12) {
      if (y === 7 || y === 14 || x === 3 || x === 12) return c.ink;
      if (x >= 7 && x <= 8 && y >= 9 && y <= 12) return c.ink;
      return y < 9 ? c.cat : c.terracotta.DEFAULT;
    }
    return null;
  },
  island: islandPaint,
  islandLocked: islandPaint, // drawn the same; the map greys it out
  boat: boatPaint,
  quizHall,
  tutorCafe,
  studyStudio,
  audioStudio,
  teachBackArena,
};

export function artSvg(name: string, w: number, h: number): string | null {
  const paint = ART[name];
  return paint ? svgRects(w, h, paint) : null;
}

/** The sea behind the map: a few pixel waves on a 64×32 tile shown at 2× (128px × 64px, the
 * `water` keyframes move exactly one tile so the loop is seamless). */
export function waterTileUrl(): string {
  const wave = (x: number, y: number, fill: string) =>
    [
      [0, 1],
      [1, 0],
      [2, 0],
      [3, 1],
      [4, 1],
      [5, 0],
    ]
      .map(
        ([dx, dy]) => `<rect x="${x + dx!}" y="${y + dy!}" width="1" height="1" fill="${fill}"/>`,
      )
      .join("");
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="64" viewBox="0 0 64 32" shape-rendering="crispEdges">` +
    `<rect width="64" height="32" fill="${c.sea.DEFAULT}"/>` +
    wave(4, 3, c.sea.light) +
    wave(38, 7, c.sea.foam) +
    wave(18, 16, c.sea.foam) +
    wave(52, 21, c.sea.light) +
    wave(28, 27, c.sea.light) +
    `</svg>`;
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
}

/** The island page's ground: one big pixel island (160×110 grid, the scene's 16:11) with sandy
 * paths from the explorer to each building. Positions are in % of the scene. */
export function islandSceneSvg(
  spots: { x: number; y: number }[],
  centre: { x: number; y: number },
): string {
  const W = 160;
  const H = 110;
  const pts = spots.map((p) => [(p.x / 100) * W, (p.y / 100) * H] as const);
  const cx0 = (centre.x / 100) * W;
  const cy0 = (centre.y / 100) * H;
  const nearPath = (x: number, y: number) =>
    pts.some(([bx, by]) => {
      const dx = bx - cx0;
      const dy = by - cy0;
      const t = Math.max(0, Math.min(1, ((x - cx0) * dx + (y - cy0) * dy) / (dx * dx + dy * dy)));
      return Math.hypot(x - (cx0 + t * dx), y - (cy0 + t * dy)) < 1.6;
    });
  const clear = (x: number, y: number) =>
    Math.hypot(x - cx0, y - cy0) > 9 && pts.every(([bx, by]) => Math.hypot(x - bx, y - by) > 15);
  const trees = new Set<string>();
  for (let ty = 5; ty < H; ty += 11) {
    for (let tx = 4 + (Math.floor(ty / 11) % 2) * 6; tx < W; tx += 13) {
      const jx = tx + ((tx * 7 + ty * 13) % 5) - 2;
      const jy = ty + ((tx * 11 + ty * 3) % 3) - 1;
      if (clear(jx, jy) && !nearPath(jx, jy)) trees.add(`${jx},${jy}`);
    }
  }
  const ground = (x: number, y: number) => {
    const nx = (x + 0.5 - 80) / 74;
    const ny = (y + 0.5 - 56) / 50;
    return nx * nx + ny * ny + 0.05 * Math.sin(x * 0.21) + 0.05 * Math.cos(y * 0.29 + x * 0.07);
  };
  const paint: Paint = (x, y) => {
    const d = ground(x, y);
    if (d >= 1) return null;
    if (d >= 0.88) return (x * 5 + y * 3) % 13 === 0 ? c.sea.foam : c.sea.light;
    if (d >= 0.74) return (x * 3 + y) % 17 === 0 ? c.whitewash : c.sand.DEFAULT;
    if (d >= 0.71) return c.sand.dark;
    // tree: a 3×2 crown, shaded underneath, trunk below
    for (let dx = 0; dx < 3; dx++) {
      for (let dy = 0; dy < 2; dy++) {
        if (trees.has(`${x - dx},${y - dy}`)) return dy === 1 ? c.olive.ink : c.olive.DEFAULT;
      }
    }
    if (trees.has(`${x - 1},${y - 2}`)) return c.terracotta.ink;
    if (nearPath(x, y)) return c.sand.DEFAULT;
    return (x * 7 + y * 3) % 41 === 0 ? c.olive.DEFAULT : c.olive.light;
  };
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" shape-rendering="crispEdges">` +
    svgRects(W, H, paint) +
    `</svg>`
  );
}
