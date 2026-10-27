import type { ReactNode } from "react";
import { cx } from "./cx";
import { Sprite } from "./sprite/Sprite";
import type { SpriteName } from "./sprite/registry";

export type BannerKind = "queue" | "offline" | "quickMode" | "placement";

const STYLES: Record<BannerKind, string> = {
  queue: "border-sea-ink bg-sea-foam text-ink",
  offline: "border-ink bg-ink text-white",
  quickMode: "border-sea-ink bg-white text-sea-ink",
  placement: "border-primary bg-primary/10 text-ink",
};

const ICONS: Partial<Record<BannerKind, SpriteName>> = {
  queue: "hourglass",
  placement: "lantern",
};

interface BannerProps {
  kind: BannerKind;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}

/** Status line for the queue, offline demo mode, quick mode and the placement prompt. */
export function Banner({ kind, children, action, className }: BannerProps) {
  const icon = ICONS[kind];
  return (
    <div
      role="status"
      aria-live="polite"
      data-kind={kind}
      className={cx(
        "flex items-center gap-3 rounded-pixel-step border-2 px-4 py-3 font-semibold",
        STYLES[kind],
        className,
      )}
    >
      {icon && <Sprite name={icon} scale={2} />}
      <span className="flex-1">{children}</span>
      {action}
    </div>
  );
}
