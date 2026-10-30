import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { JobView } from "@/api/client";
import { Banner, Bidi, Chip, LoadingStages, type LoadingTip, PixelButton } from "@/components";
import { useJob } from "@/hooks/useJob";

interface JobProgressProps {
  jobId: string;
  /** Class Wisdom tip for the loading screen (M6), or a general study tip. */
  tip?: LoadingTip;
  children: (result: NonNullable<JobView["result"]>, job: JobView) => ReactNode;
}

/** The loading screen for any AI action: real stages, queue position + ETA, quick mode, cancel. */
export function JobProgress({ jobId, tip, children }: JobProgressProps) {
  const { t } = useTranslation();
  const j = useJob(jobId);

  if (!j.job) {
    return j.error ? <Banner kind="error">{t(j.error)}</Banner> : null;
  }
  const job = j.job;

  return (
    <div className="flex flex-col gap-4" data-status={job.status}>
      {job.status === "queued" && j.queuePosition !== null && (
        <Banner
          kind="queue"
          action={
            <PixelButton variant="secondary" onClick={() => j.cancel()} disabled={j.cancelling}>
              {t("jobs.cancel")}
            </PixelButton>
          }
        >
          {t("jobs.queue", { position: j.queuePosition, seconds: j.etaS ?? 0 })}
          {j.waitingReason && (
            <span className="block text-small font-normal">
              {t(`jobs.waiting.${j.waitingReason}`, { defaultValue: t("jobs.waiting.default") })}
            </span>
          )}
        </Banner>
      )}
      {j.cancelError && <Banner kind="error">{t("errors.job_not_cancellable")}</Banner>}

      {!j.isTerminal && <LoadingStages stages={j.stages} tip={tip} />}

      {job.status === "done" && job.result && (
        <div className="flex flex-col gap-3">
          {j.quickMode && (
            <div className="flex flex-wrap items-center gap-2">
              <Chip kind="quickMode">{t("chip.quickMode")}</Chip>
              <span className="text-small text-ink/70">{t("banner.quickMode")}</span>
            </div>
          )}
          {children(job.result, job)}
        </div>
      )}
      {job.status === "failed" && (
        <Banner kind="error">{t(job.error ?? "errors.ai_failed")}</Banner>
      )}
      {job.status === "cancelled" && <Banner kind="placement">{t("jobs.cancelled")}</Banner>}
      <p className="sr-only" aria-live="polite">
        <Bidi>{t(`jobs.status.${job.status}`)}</Bidi>
      </p>
    </div>
  );
}
