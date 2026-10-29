import { color } from "@/theme/tokens";
import { type AvatarLook, DEFAULT_LOOK, OUTFIT_SWATCH, SKIN_SWATCH } from "./avatarLook";
import { cx } from "./cx";

/** Placeholder pixel avatar on a 16×16 grid (crisp at any integer scale). Not a likeness of anyone:
 * a few choices only, nothing identifying (PRODUCT.md §Privacy). */
export function Avatar({
  look,
  size = 40,
  label,
  className,
}: {
  look?: AvatarLook | null;
  size?: number;
  label?: string;
  className?: string;
}) {
  const l = look ?? DEFAULT_LOOK;
  const skin = SKIN_SWATCH[l.skin] ?? SKIN_SWATCH.s2!;
  const outfit = OUTFIT_SWATCH[l.outfit] ?? OUTFIT_SWATCH.o1!;
  const ink = color.ink;
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      shapeRendering="crispEdges"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={cx("pixelated shrink-0 rounded-pixel-step bg-sand", className)}
    >
      {/* body + head */}
      <rect x="3" y="11" width="10" height="5" fill={outfit} />
      <rect x="5" y="4" width="6" height="7" fill={skin} />
      <rect x="6" y="7" width="1" height="1" fill={ink} />
      <rect x="9" y="7" width="1" height="1" fill={ink} />
      <rect x="7" y="9" width="2" height="1" fill={color.terracotta.ink} />
      {/* hair */}
      <rect x="5" y="3" width="6" height="2" fill={ink} />
      {l.extra === "cap" && (
        <>
          <rect x="4" y="2" width="8" height="2" fill={color.primary.DEFAULT} />
          <rect x="10" y="4" width="3" height="1" fill={color.primary.dark} />
        </>
      )}
      {l.extra === "glasses" && <rect x="5" y="7" width="6" height="1" fill={ink} />}
      {l.extra === "scarf" && (
        <rect x="4" y="10" width="8" height="2" fill={color.primary.DEFAULT} />
      )}
      {l.extra === "chechia" && (
        <rect x="5" y="1" width="6" height="3" fill={color.danger.DEFAULT} />
      )}
      {l.extra === "headphones" && (
        <>
          <rect x="4" y="2" width="8" height="1" fill={ink} />
          <rect x="3" y="6" width="2" height="3" fill={color.sea.ink} />
          <rect x="11" y="6" width="2" height="3" fill={color.sea.ink} />
        </>
      )}
    </svg>
  );
}
