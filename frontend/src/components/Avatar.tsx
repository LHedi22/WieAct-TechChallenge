import { color } from "@/theme/tokens";
import {
  type AvatarLook,
  DEFAULT_LOOK,
  HAIR_SWATCH,
  OUTFIT_SWATCH,
  SKIN_SWATCH,
} from "./avatarLook";
import { cx } from "./cx";

/** [x, y, width, height, fill, opacity?] on the 24×24 grid. */
type Px = [number, number, number, number, string, number?];

const HAIR: Record<string, (c: string) => Px[]> = {
  short: (c) => [
    [7, 4, 10, 1, c],
    [6, 5, 12, 3, c],
    [6, 8, 1, 2, c],
    [17, 8, 1, 2, c],
    [8, 8, 3, 1, c],
  ],
  curly: (c) => [
    [6, 3, 3, 1, c],
    [10, 2, 4, 2, c],
    [15, 3, 3, 1, c],
    [5, 4, 14, 4, c],
    [5, 8, 1, 4, c],
    [18, 8, 1, 4, c],
    [7, 8, 2, 1, c],
    [11, 8, 2, 1, c],
    [15, 8, 2, 1, c],
  ],
  long: (c) => [
    [7, 4, 10, 1, c],
    [6, 5, 12, 3, c],
    [5, 6, 2, 12, c],
    [17, 6, 2, 12, c],
    [8, 8, 4, 1, c],
  ],
  bun: (c) => [
    [10, 1, 4, 3, c],
    [7, 4, 10, 1, c],
    [6, 5, 12, 3, c],
    [6, 8, 1, 2, c],
    [17, 8, 1, 2, c],
  ],
  spiky: (c) => [
    [7, 2, 2, 2, c],
    [11, 1, 2, 3, c],
    [15, 2, 2, 2, c],
    [6, 4, 12, 4, c],
    [9, 8, 2, 1, c],
    [13, 8, 2, 1, c],
  ],
  // headscarf: frames the face and drapes over the neck
  wrap: () => [
    [7, 3, 10, 1, color.bougainvillea],
    [5, 4, 14, 5, color.bougainvillea],
    [5, 9, 2, 9, color.bougainvillea],
    [17, 9, 2, 9, color.bougainvillea],
    [7, 17, 10, 3, color.bougainvillea],
    [6, 5, 12, 1, color.whitewash, 0.35],
  ],
};

const EXTRA: Record<string, Px[]> = {
  cap: [
    [6, 3, 12, 1, color.primary.DEFAULT],
    [5, 4, 14, 3, color.primary.DEFAULT],
    [11, 4, 2, 1, color.whitewash],
    [14, 7, 7, 1, color.primary.dark],
  ],
  glasses: [
    [8, 10, 3, 4, color.sea.foam, 0.35],
    [13, 10, 3, 4, color.sea.foam, 0.35],
    [8, 10, 8, 1, color.ink],
    [6, 11, 2, 1, color.ink],
    [16, 11, 2, 1, color.ink],
  ],
  scarf: [
    [6, 17, 12, 3, color.primary.DEFAULT],
    [6, 18, 12, 1, color.primary.light],
    [14, 20, 2, 3, color.primary.dark],
  ],
  chechia: [
    [8, 0, 8, 1, color.danger.DEFAULT],
    [7, 1, 10, 5, color.danger.DEFAULT],
    [7, 5, 10, 1, color.ink, 0.25],
    [16, 1, 1, 5, color.ink],
  ],
  headphones: [
    [6, 3, 12, 1, color.ink],
    [5, 4, 1, 5, color.ink],
    [18, 4, 1, 5, color.ink],
    [4, 9, 3, 5, color.sea.ink],
    [17, 9, 3, 5, color.sea.ink],
  ],
};

/** Pixel avatar on a 24×24 grid. Not a likeness of anyone: a few choices only, nothing
 * identifying (PRODUCT.md §Privacy). */
export function Avatar({
  look,
  size = 40,
  label,
  bare,
  className,
}: {
  look?: AvatarLook | null;
  size?: number;
  label?: string;
  /** No background tile (the explorer standing in a scene). */
  bare?: boolean;
  className?: string;
}) {
  const l = look ?? DEFAULT_LOOK;
  const skin = SKIN_SWATCH[l.skin] ?? SKIN_SWATCH.s2!;
  const outfit = OUTFIT_SWATCH[l.outfit] ?? OUTFIT_SWATCH.o1!;
  const hair = (HAIR[l.hair ?? "short"] ?? HAIR.short!)(
    HAIR_SWATCH[l.hair_color ?? "c1"] ?? HAIR_SWATCH.c1!,
  );
  const ink = color.ink;
  const px: Px[] = [
    // shoulders, collar shade, neck
    [6, 19, 12, 1, outfit],
    [4, 20, 16, 4, outfit],
    [9, 19, 6, 2, ink, 0.18],
    [10, 17, 4, 3, skin],
    // ears + head with stepped corners
    [5, 10, 1, 3, skin],
    [18, 10, 1, 3, skin],
    [7, 6, 10, 1, skin],
    [6, 7, 12, 9, skin],
    [7, 16, 10, 1, skin],
    [8, 17, 8, 1, skin],
    // eyes with a highlight, cheeks, smile
    [9, 11, 2, 2, ink],
    [13, 11, 2, 2, ink],
    [9, 11, 1, 1, color.whitewash],
    [13, 11, 1, 1, color.whitewash],
    [7, 13, 2, 1, color.bougainvillea, 0.45],
    [15, 13, 2, 1, color.bougainvillea, 0.45],
    [10, 14, 1, 1, color.terracotta.ink],
    [13, 14, 1, 1, color.terracotta.ink],
    [11, 15, 2, 1, color.terracotta.ink],
    ...hair,
    ...(l.extra ? (EXTRA[l.extra] ?? []) : []),
  ];
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      shapeRendering="crispEdges"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cx("pixelated shrink-0 rounded-pixel-step", !bare && "bg-sea-foam", className)}
    >
      {px.map(([x, y, w, h, fill, opacity], i) => (
        <rect key={i} x={x} y={y} width={w} height={h} fill={fill} opacity={opacity} />
      ))}
    </svg>
  );
}
