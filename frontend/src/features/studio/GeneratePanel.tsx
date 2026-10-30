import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import type { StudioPay } from "@/api/client";
import { Banner, Bidi, Chip, PixelButton, PixelPanel } from "@/components";
import { cx } from "@/components/cx";
import { useNumberFormat } from "@/components/useNumberFormat";
import { PoolCard } from "@/features/pool/PoolCard";
import { useWallet } from "@/hooks/useSession";

/** Shared material not made yet (study pack, audio episode): what it costs, who pays (me or the
 * Class Pool), and the pool itself. */
export function GeneratePanel({
  cost,
  poolBalance,
  title,
  body,
  worldId,
  busy,
  onGenerate,
}: {
  cost: number;
  poolBalance: number;
  title: string;
  body: string;
  worldId: string;
  busy: boolean;
  onGenerate: (pay: StudioPay) => void;
}) {
  const { t } = useTranslation("studio");
  const { t: tc } = useTranslation();
  const nf = useNumberFormat();
  const coins = useWallet().data?.coins ?? 0;
  const poolOk = poolBalance >= cost;
  const [pay, setPay] = useState<StudioPay>(poolOk && coins < cost ? "pool" : "me");
  const name = useId();
  const after = pay === "me" ? coins - cost : poolBalance - cost;

  return (
    <div className="flex flex-col gap-4">
      <PixelPanel className="flex flex-col gap-4" data-testid="generate-panel">
        <h2 className="text-h2">{title}</h2>
        <p>{body}</p>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 font-semibold">{t("make.who")}</legend>
          {(["me", "pool"] as const).map((p) => (
            <label
              key={p}
              className={cx(
                "flex min-h-11 items-center gap-3 rounded-pixel-step border-2 px-3",
                pay === p ? "border-ink bg-sand/30" : "border-sand bg-white",
                p === "pool" && !poolOk && "opacity-60",
              )}
            >
              <input
                type="radio"
                name={name}
                value={p}
                checked={pay === p}
                disabled={p === "pool" && !poolOk}
                onChange={() => setPay(p)}
              />
              <span className="flex-1">
                {p === "me"
                  ? t("make.me", { count: coins })
                  : t("make.pool", { count: poolBalance })}
              </span>
            </label>
          ))}
        </fieldset>
        <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1">
          <dt>{t("make.cost")}</dt>
          <dd className="text-end">
            <Chip kind="cost">{tc("chip.cost", { count: cost })}</Chip>
          </dd>
          <dt>{pay === "me" ? t("make.after") : t("make.poolAfter")}</dt>
          <dd className={cx("text-end font-semibold", after < 0 && "text-danger")}>
            <Bidi>{nf.format(Math.max(after, 0))}</Bidi>
          </dd>
        </dl>
        {pay === "me" && after < 0 && <Banner kind="error">{t("make.short")}</Banner>}
        <PixelButton
          variant="spend"
          className="self-end"
          disabled={busy || after < 0}
          onClick={() => onGenerate(pay)}
        >
          {t("make.go")}
        </PixelButton>
      </PixelPanel>
      <PoolCard worldId={worldId} />
    </div>
  );
}
