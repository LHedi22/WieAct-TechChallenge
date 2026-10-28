import { useTranslation } from "react-i18next";
import { Banner, Chip } from "@/components";
import { useSystemStatus } from "@/hooks/useSystemStatus";

/** Dev-only Local/Cloud/Mock badge (ARCHITECTURE.md §Providers). Never shown in production builds. */
export function ProviderBadge() {
  const { t } = useTranslation();
  const { data } = useSystemStatus();
  if (!import.meta.env.DEV || !data) return null;
  const label = t(`provider.${data.provider}`);
  const auto = data.configured_provider === "auto" ? ` · ${t("provider.auto")}` : "";
  return (
    <Chip kind="confidence" className="self-start">
      {t("provider.label")}: {label}
      {auto}
    </Chip>
  );
}

/** Shown on every screen when new AI actions are paused (outside our slot in production). */
export function OfflineBanner() {
  const { t } = useTranslation();
  const { data } = useSystemStatus();
  if (!data?.offline_demo_mode) return null;
  return <Banner kind="offline">{t("banner.offline")}</Banner>;
}
