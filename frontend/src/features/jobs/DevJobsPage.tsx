import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type ApiError } from "@/api/client";
import { useUiStore } from "@/app/uiStore";
import { Banner, LanguageSwitcher, PixelButton, PixelPanel, SoftCard } from "@/components";
import { cx } from "@/components/cx";
import { JobProgress } from "./JobProgress";
import { ProviderBadge } from "./ProviderBadge";

type Lane = "interactive" | "background";

interface DemoSummary {
  summary?: { summary?: string; key_points?: string[] };
  model_tier?: string;
}

/** /dev/jobs — drives the M1 demo job through useJob + LoadingStages + queue/quick-mode UI. */
export function DevJobsPage() {
  const { t } = useTranslation("dev");
  const { t: tc } = useTranslation();
  const language = useUiStore((s) => s.language);
  const [lane, setLane] = useState<Lane>("interactive");
  const [jobId, setJobId] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => api.startDemoJob({ lane, language }),
    onSuccess: (created) => setJobId(created.job_id),
  });

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-8 sm:px-8">
      <header className="flex flex-col gap-3">
        <h1 className="text-h1">{t("title")}</h1>
        <p className="text-ink/70">{t("intro")}</p>
        <ProviderBadge />
        <LanguageSwitcher />
      </header>

      <PixelPanel className="flex flex-col gap-4">
        <fieldset className="flex flex-wrap items-center gap-2">
          <legend className="mb-2 font-semibold">{t("lane")}</legend>
          {(["interactive", "background"] as const).map((l) => (
            <button
              key={l}
              type="button"
              aria-pressed={lane === l}
              onClick={() => setLane(l)}
              className={cx(
                "min-h-11 rounded-pixel-step border-2 px-3 py-1 font-semibold",
                lane === l ? "border-ink bg-primary text-white" : "border-sand bg-white",
              )}
            >
              {t(`lanes.${l}`)}
            </button>
          ))}
        </fieldset>
        <PixelButton
          onClick={() => start.mutate()}
          disabled={start.isPending}
          className="self-start"
        >
          {t("start")}
        </PixelButton>
        {start.error && <Banner kind="error">{tc((start.error as ApiError).key)}</Banner>}
      </PixelPanel>

      {jobId && (
        <JobProgress key={jobId} jobId={jobId} tip={tc("wisdom.sample")}>
          {(result) => {
            const r = result as DemoSummary;
            return (
              <SoftCard className="flex flex-col gap-2">
                <h2 className="text-h3">{t("result")}</h2>
                <p>{r.summary?.summary}</p>
                <ul className="list-disc ps-6">
                  {r.summary?.key_points?.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </SoftCard>
            );
          }}
        </JobProgress>
      )}
    </main>
  );
}
