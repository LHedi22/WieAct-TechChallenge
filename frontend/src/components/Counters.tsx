import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Bidi } from "./Bidi";
import { cx } from "./cx";
import { Sprite } from "./sprite/Sprite";
import type { SpriteName } from "./sprite/registry";
import { useNumberFormat } from "./useNumberFormat";

function Counter({
  icon,
  iconLabel,
  children,
  className,
}: {
  icon: SpriteName;
  iconLabel: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-2 rounded-pixel-step border-2 border-sand bg-white px-3 py-1.5",
        className,
      )}
    >
      <Sprite name={icon} scale={2} alt={iconLabel} />
      <span>{children}</span>
    </span>
  );
}

/** Values come from the API (/api/wallet, /api/economy) — never hard-code a coin amount. */
export function CoinCounter({ value }: { value: number }) {
  const { t } = useTranslation();
  const nf = useNumberFormat();
  return (
    <Counter icon="coin" iconLabel={t("icons.coin")}>
      <Bidi className="font-semibold">{nf.format(value)}</Bidi>{" "}
      {t("counters.coins", { count: value })}
    </Counter>
  );
}

export function PointsCounter({ value }: { value: number }) {
  const { t } = useTranslation();
  const nf = useNumberFormat();
  return (
    <Counter icon="star" iconLabel={t("icons.star")}>
      <Bidi className="font-semibold">{nf.format(value)}</Bidi>{" "}
      {t("counters.points", { count: value })}
    </Counter>
  );
}

export function StreakCounter({ days }: { days: number }) {
  const { t } = useTranslation();
  const nf = useNumberFormat();
  return (
    <Counter icon="flame" iconLabel={t("icons.flame")}>
      <Bidi className="font-semibold">{nf.format(days)}</Bidi>{" "}
      {t("counters.streak", { count: days })}
    </Counter>
  );
}

export function RefillTimer({ seconds }: { seconds: number }) {
  const { t } = useTranslation();
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return (
    <Counter icon="hourglass" iconLabel={t("icons.hourglass")}>
      {t("counters.refillIn")}{" "}
      <Bidi className="font-semibold">{t("counters.duration", { h, m })}</Bidi>
    </Counter>
  );
}
