import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "./cx";
import { Mascot } from "./Mascot";
import { SoftCard } from "./surfaces";

export type StageState = "done" | "inProgress" | "next";

/** A loading-screen tip with its own label (Class wisdom, or a general study tip). A bare node is
 * labelled "Class wisdom". */
export type LoadingTip = ReactNode | { title: string; body: ReactNode };

function isTitled(tip: LoadingTip): tip is { title: string; body: ReactNode } {
  return typeof tip === "object" && tip !== null && "body" in tip && "title" in tip;
}

export interface Stage {
  /** Backend stage key (jobs.stage), e.g. "reading_chapter" → i18n loading.stages.<key>. */
  key: string;
  state: StageState;
}

const MARK: Record<StageState, string> = {
  done: "border-olive-ink bg-olive-ink",
  inProgress: "border-primary bg-primary/20 motion-safe:animate-pulse",
  next: "border-ink/40 bg-white",
};

/** Real progress from the job's stages (useJob) — never a bare spinner. */
export function LoadingStages({
  stages,
  tip,
  showMascot = true,
}: {
  stages: Stage[];
  tip?: LoadingTip;
  showMascot?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
      {showMascot && <Mascot pose="thinking" scale={3} />}
      <div className="flex flex-1 flex-col gap-3">
        <ol aria-live="polite" className="flex flex-col gap-2">
          {stages.map((s) => (
            <li key={s.key} data-state={s.state} className="flex items-center gap-3">
              <span
                aria-hidden
                className={cx("size-4 rounded-pixel-step border-2", MARK[s.state])}
              />
              <span
                className={cx(
                  s.state === "next" && "text-ink/70",
                  s.state === "inProgress" && "font-semibold",
                )}
              >
                {t(`loading.stages.${s.key}`)}
              </span>
              <span className="sr-only">({t(`loading.${s.state}`)})</span>
            </li>
          ))}
        </ol>
        {tip && (
          <SoftCard className="bg-sand/20">
            <p className="text-small font-semibold text-olive-ink">
              {isTitled(tip) ? tip.title : t("wisdom.title")}
            </p>
            <div>{isTitled(tip) ? tip.body : tip}</div>
          </SoftCard>
        )}
      </div>
    </div>
  );
}
