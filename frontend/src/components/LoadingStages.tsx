import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "./cx";
import { Mascot } from "./Mascot";
import { SoftCard } from "./surfaces";

export type StageState = "done" | "inProgress" | "next";

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
  tip?: ReactNode;
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
            <p className="text-small font-semibold text-olive-ink">{t("wisdom.title")}</p>
            <p>{tip}</p>
          </SoftCard>
        )}
      </div>
    </div>
  );
}
