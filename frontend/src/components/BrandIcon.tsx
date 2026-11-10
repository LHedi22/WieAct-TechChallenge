/** Captain Cat app icon (design/assets/brand), shown next to the app name. Decorative. */
export function BrandIcon({ size = 32 }: { size?: number }) {
  return (
    <img
      src="/brand/icon-64.png"
      width={size}
      height={size}
      alt=""
      aria-hidden
      className="shrink-0 [image-rendering:pixelated]"
    />
  );
}
