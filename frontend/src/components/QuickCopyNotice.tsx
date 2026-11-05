import { useTranslation } from "react-i18next";
import { Chip } from "./Chip";
import { PixelButton } from "./PixelButton";

interface QuickCopyNoticeProps {
  busy?: boolean;
  onUpgrade: () => void;
}

/** Shown on class material written by the faster model while the platform was busy (audit
 * F-QUICK-1). Anyone in the class can ask for the full version; it is free (already paid for). */
export function QuickCopyNotice({ busy = false, onUpgrade }: QuickCopyNoticeProps) {
  const { t } = useTranslation("common");
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-pixel-step border-2 border-sea-ink bg-white p-3"
    >
      <Chip kind="quickMode">{t("chip.quickMode")}</Chip>
      <p className="min-w-0 flex-1 text-small">{t("quickCopy.body")}</p>
      <PixelButton variant="secondary" disabled={busy} onClick={onUpgrade}>
        {t("quickCopy.upgrade")}
      </PixelButton>
    </div>
  );
}
