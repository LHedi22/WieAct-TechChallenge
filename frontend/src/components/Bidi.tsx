import type { ReactNode } from "react";

/**
 * Isolates Latin or numeric fragments inside Arabic text (nicknames, "B2", "7 / 10", "(you)") so
 * the bidi algorithm can't reorder them (DESIGN.md §RTL).
 */
export function Bidi({ children, className }: { children: ReactNode; className?: string }) {
  return <bdi className={className}>{children}</bdi>;
}
