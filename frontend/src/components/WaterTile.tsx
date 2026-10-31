import type { ReactNode } from "react";
import { cx } from "./cx";
import { waterTileUrl } from "./sprite/art";

const WATER = waterTileUrl();

/** Animated sea background; still under prefers-reduced-motion and the in-app setting. */
export function WaterTile({ className, children }: { className?: string; children?: ReactNode }) {
  return (
    <div
      className={cx("water-tile pixelated animate-water", className)}
      style={{ backgroundImage: WATER }}
    >
      {children}
    </div>
  );
}
