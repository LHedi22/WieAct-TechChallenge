import { useTranslation } from "react-i18next";
import { Banner, Chip } from "@/components";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { numberLocale } from "@/i18n/languages";

/** Dev-only Local/Cloud/Mock badge (ARCHITECTURE.md §Providers). Never shown in production builds. */
export function ProviderBadge({ className }: { className?: string }) {
  const { t } = useTranslation();
  const { data } = useSystemStatus();
  if (!import.meta.env.DEV || !data) return null;
  const label = t(`provider.${data.provider}`);
  const auto = data.configured_provider === "auto" ? ` · ${t("provider.auto")}` : "";
  return (
    <Chip kind="confidence" className={className}>
      {t("provider.label")}: {label}
      {auto}
    </Chip>
  );
}

/** Shown on every screen when new AI actions are paused (outside our slot in production), with
 * when they come back (Tunis time, in the student's locale). */
export function OfflineBanner() {
  const { t, i18n } = useTranslation();
  const { data } = useSystemStatus();
  if (!data?.offline_demo_mode) return null;
  const when = data.next_slot_start
    ? new Intl.DateTimeFormat(numberLocale(i18n.language), {
        weekday: "long",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Africa/Tunis", // slots are defined in Tunis time
        hourCycle: "h23", // "00:00", not an ambiguous "12:00 AM"
      }).format(new Date(data.next_slot_start))
    : null;
  return (
    <div className="sticky top-0 z-40 bg-whitewash px-4 pt-2">
      <Banner kind="offline">
        {t("banner.offline")} {when && t("banner.offlineUntil", { when })}
      </Banner>
    </div>
  );
}
