import { useTranslation } from "react-i18next";
import { useOnce } from "@/hooks/useOnce";
import type { components } from "@/api/schema";
import { Chip } from "./Chip";
import { PixelButton } from "./PixelButton";

type Preparing = components["schemas"]["Preparing"];

interface PreparingNoteProps {
  preparing: Preparing;
  /** Promote the class's background job to "needed now" (free). Omitted: no button. */
  onGetItNow?: () => void;
  busy?: boolean;
  /** Press "Get it now" on mount: the student already asked for it in the building dialog. */
  autoStart?: boolean;
  /** Short form for dialogs and banners: no explanation line. */
  compact?: boolean;
}

/** Background prefetch in progress: "Being prepared · about N min · Place k in line", and
 * "Get it now" to move it ahead of the background queue. */
export function PreparingNote({
  preparing,
  onGetItNow,
  busy = false,
  autoStart = false,
  compact = false,
}: PreparingNoteProps) {
  const { t } = useTranslation("common");
  const minutes = Math.max(1, Math.ceil(preparing.eta_s / 60));
  const line = [
    t("prefetch.preparing", { count: minutes }),
    preparing.queue_position != null &&
      t("prefetch.inLine", { position: preparing.queue_position }),
  ]
    .filter(Boolean)
    .join(" · ");
  if (compact) {
    return (
      <span className="text-small text-ink/70" role="status">
        {line}
      </span>
    );
  }
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-pixel-step border-2 border-olive-ink bg-white p-3"
    >
      <Chip kind="ready">{t("chip.free")}</Chip>
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{line}</p>
        <p className="text-small text-ink/70">{t("prefetch.body")}</p>
      </div>
      {onGetItNow && autoStart && <Once fn={onGetItNow} />}
      {onGetItNow && (
        <PixelButton variant="spend" disabled={busy} onClick={onGetItNow}>
          {t("prefetch.getItNow")}
        </PixelButton>
      )}
    </div>
  );
}

function Once({ fn }: { fn: () => void }) {
  useOnce(fn);
  return null;
}
