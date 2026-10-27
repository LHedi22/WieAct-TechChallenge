import { useTranslation } from "react-i18next";
import { Bidi } from "./Bidi";
import { cx } from "./cx";

export function ProgressBar({
  value,
  max,
  label,
  className,
}: {
  value: number;
  max: number;
  label: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div className={cx("flex items-center gap-3", className)}>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={value}
        className="h-4 flex-1 overflow-hidden rounded-pixel-step border-2 border-ink bg-sand"
      >
        <div className="h-full bg-olive" style={{ inlineSize: `${pct}%` }} />
      </div>
      <Bidi className="text-small font-semibold">{t("progress.ratio", { value, max })}</Bidi>
    </div>
  );
}

export type SegmentState = "correct" | "wrong" | "current" | "pending";

const SEGMENT: Record<SegmentState, string> = {
  correct: "bg-olive",
  wrong: "bg-terracotta",
  current: "bg-primary",
  pending: "bg-sand",
};

/** Quiz progress (Q4/10): one segment per question. */
export function SegmentedProgress({
  segments,
  className,
}: {
  segments: SegmentState[];
  className?: string;
}) {
  const { t } = useTranslation();
  const current = Math.max(0, segments.indexOf("current")) + 1;
  return (
    <div className={cx("flex items-center gap-3", className)}>
      <ol
        aria-label={t("progress.questionOf", { n: current, total: segments.length })}
        className="flex h-4 flex-1 gap-0.5 rounded-pixel-step border-2 border-ink bg-ink"
      >
        {segments.map((s, i) => (
          <li key={i} data-state={s} className={cx("flex-1", SEGMENT[s])} />
        ))}
      </ol>
      <Bidi className="text-small font-semibold">
        {t("progress.questionShort", { n: current })}
      </Bidi>
    </div>
  );
}

// Literal class names so Tailwind keeps them (no dynamic `stroke-island-${n}`).
const ISLAND_STROKE = [
  "stroke-island-1",
  "stroke-island-2",
  "stroke-island-3",
  "stroke-island-4",
  "stroke-island-5",
  "stroke-island-6",
] as const;

export type IslandAccent = 1 | 2 | 3 | 4 | 5 | 6;

/** Chapter/course mastery 0–1, drawn in the island's accent colour. */
export function MasteryRing({
  value,
  accent,
  size = 40,
}: {
  value: number;
  accent: IslandAccent;
  size?: number;
}) {
  const { t } = useTranslation();
  const r = 15;
  const circumference = 2 * Math.PI * r;
  const v = Math.min(1, Math.max(0, value));
  const percent = Math.round(v * 100);
  return (
    <svg
      viewBox="0 0 40 40"
      width={size}
      height={size}
      role="img"
      aria-label={t("progress.mastery", { percent })}
    >
      <circle cx="20" cy="20" r={r} fill="none" strokeWidth="6" className="stroke-sand" />
      <circle
        cx="20"
        cy="20"
        r={r}
        fill="none"
        strokeWidth="6"
        strokeDasharray={`${v * circumference} ${circumference}`}
        transform="rotate(-90 20 20)"
        className={ISLAND_STROKE[accent - 1]}
      />
    </svg>
  );
}
