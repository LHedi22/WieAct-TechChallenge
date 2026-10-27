import type { HTMLAttributes } from "react";
import { cx } from "./cx";

/** Ink outline, stepped corners: dialogs, map labels, focus surfaces. */
export function PixelPanel({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx("rounded-pixel-step border-2 border-ink bg-white p-4 shadow-panel", className)}
      {...rest}
    />
  );
}

/** Sand outline, rounded 8: lists, challenges, feeds. */
export function SoftCard({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("rounded-soft border-2 border-sand bg-white p-4", className)} {...rest} />
  );
}
