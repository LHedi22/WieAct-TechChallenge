export type SpriteScale = 1 | 2 | 3 | 4 | 5 | 6;

/** Pixel art is never resampled at fractional sizes: round and clamp to 1–6. */
export function toIntegerScale(scale: number): SpriteScale {
  const s = Math.min(6, Math.max(1, Math.round(scale)));
  if (s !== scale && import.meta.env.DEV) {
    console.warn(`Sprite: scale ${scale} is not an integer 1–6, using ${s}`);
  }
  return s as SpriteScale;
}
