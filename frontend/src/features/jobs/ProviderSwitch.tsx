import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import { Chip } from "@/components";
import { cx } from "@/components/cx";
import { useJob } from "@/hooks/useJob";
import { useSystemStatus } from "@/hooks/useSystemStatus";

const CHOICES = ["cloud", "local"] as const;
type Choice = (typeof CHOICES)[number];

const PAUSED: Record<string, string> = {
  cloud_not_configured: "provider.pausedNoKey",
  outside_slot: "provider.pausedSlot",
  blocked: "provider.pausedBlocked",
};

/** Development: pick the competition's cloud models or your own Ollama models at runtime
 * (PUT /api/system/provider). Switching re-tags and re-indexes the course material with the
 * picked models, and class content a weaker model made (the mock's) is written again by them.
 * Hidden in production, which always runs on the platform. */
export function ProviderSwitch({ className }: { className?: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data } = useSystemStatus();
  const [refreshJob, setRefreshJob] = useState<string | null>(null);
  const { status: refreshStatus } = useJob(refreshJob);
  const choose = useMutation({
    mutationFn: (provider: Choice) => api.chooseProvider({ provider }),
    onSuccess: (out) => {
      setRefreshJob(out.refresh_job_id ?? null);
      // Every cached view may now come from the other provider
      void qc.invalidateQueries();
    },
  });
  if (!data?.can_choose_provider) return null;

  const active = (choose.isPending ? choose.variables : undefined) ?? data.provider_choice;
  const paused = data.provider_choice && data.offline_demo_mode ? PAUSED[data.reason ?? ""] : null;
  const refreshing = refreshJob && refreshStatus !== "done" && refreshStatus !== "failed";

  return (
    <div className={cx("flex flex-col items-start gap-1", className)}>
      <div
        role="radiogroup"
        aria-label={t("provider.choose")}
        className="flex rounded-pixel-step border-2 border-ink bg-white"
      >
        {CHOICES.map((choice) => {
          const on = active === choice;
          return (
            <button
              key={choice}
              type="button"
              role="radio"
              aria-checked={on}
              title={t(`provider.${choice}Long`)}
              disabled={choose.isPending}
              onClick={() => !on && choose.mutate(choice)}
              className={cx(
                "min-h-11 px-3 text-small font-semibold",
                on ? "bg-ink text-white" : "text-ink hover:bg-sand/40",
              )}
            >
              {t(`provider.${choice}Long`)}
            </button>
          );
        })}
      </div>
      {!data.provider_choice && (
        <Chip kind="confidence">
          {t("provider.label")}: {t(`provider.${data.provider}`)}
        </Chip>
      )}
      <p role="status" aria-live="polite" className="text-small text-ink/70">
        {choose.isError
          ? t("provider.switchFailed")
          : paused
            ? t(paused)
            : refreshing
              ? t("provider.refreshing")
              : refreshStatus === "done"
                ? t("provider.refreshed")
                : null}
      </p>
    </div>
  );
}
