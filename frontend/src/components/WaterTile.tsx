import type { ReactNode } from "react";
import { cx } from "./cx";

/** Animated sea background; still under prefers-reduced-motion and the in-app setting. */
export function WaterTile({ className, children }: { className?: string; children?: ReactNode }) {
  return <div className={cx("water-tile pixelated animate-water", className)}>{children}</div>;
}
