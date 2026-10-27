import type { ReactNode } from "react";
import { cx } from "./cx";
import { Sprite } from "./sprite/Sprite";

export type ChipKind =
  | "beginner"
  | "intermediate"
  | "advanced"
  | "cost"
  | "quickMode"
  | "weakSpot"
  | "confidence"
  | "pinned";

const STYLES: Record<ChipKind, string> = {
  beginner: "border-transparent bg-primary/10 text-primary",
  intermediate: "border-transparent bg-primary text-white",
  advanced: "border-transparent bg-primary/10 text-primary-dark",
  cost: "border-transparent bg-terracotta-light/25 text-terracotta-ink",
  quickMode: "border-sea-ink bg-sea-foam text-sea-ink",
  weakSpot: "border-transparent bg-terracotta-light/30 text-terracotta-ink",
  confidence: "border-transparent bg-olive-light/30 text-olive-ink",
  pinned: "border-transparent bg-olive-ink text-white",
};

interface ChipProps {
  kind: ChipKind;
  children: ReactNode;
  className?: string;
}

/** Level, cost, Quick mode, Weak spot, Confidence, Pinned. */
export function Chip({ kind, children, className }: ChipProps) {
  return (
    <span
      data-kind={kind}
      className={cx(
        "inline-flex items-center gap-1 rounded-pixel-step border-2 px-2 py-0.5 text-small font-semibold",
        STYLES[kind],
        className,
      )}
    >
      {kind === "cost" && <Sprite name="coin" scale={1} />}
      {children}
    </span>
  );
}
