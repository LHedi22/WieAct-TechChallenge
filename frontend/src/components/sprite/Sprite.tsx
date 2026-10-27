import { cx } from "@/components/cx";
import { SPRITES, spriteSource, type SpriteName } from "./registry";
import { toIntegerScale, type SpriteScale } from "./scale";

export type { SpriteScale };

interface SpriteProps {
  name: SpriteName;
  /** Integer scales only — pixel art must never be resampled at fractional sizes. */
  scale?: SpriteScale;
  /** Accessible name; omit for decorative sprites (they are hidden from screen readers). */
  alt?: string;
  className?: string;
}

export function Sprite({ name, scale = 2, alt, className }: SpriteProps) {
  const def = SPRITES[name];
  const s = toIntegerScale(scale);
  const { src, placeholder } = spriteSource(name);
  return (
    <img
      src={src}
      width={def.w * s}
      height={def.h * s}
      alt={alt ?? ""}
      aria-hidden={alt ? undefined : true}
      draggable={false}
      data-sprite={name}
      data-placeholder={placeholder || undefined}
      className={cx("pixelated inline-block shrink-0", className)}
    />
  );
}
