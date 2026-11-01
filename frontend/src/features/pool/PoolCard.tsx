import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import { Bidi, CoinCounter, PixelButton, SoftCard } from "@/components";
import { ErrorBanner } from "@/features/worlds/parts";
import { usePool } from "./usePool";

/** The Class Pool (ECONOMY.md): coins classmates gave so shared study material can be made for
 * everyone. Balance, the last gifts (nicknames only) and "Add coins". Given coins don't come back. */
export function PoolCard({ worldId }: { worldId: string }) {
  const { t } = useTranslation("pool");
  const qc = useQueryClient();
  const pool = usePool(worldId);
  const [amount, setAmount] = useState(5);
  const inputId = useId();
  const give = useMutation({
    mutationFn: () => api.givePool(worldId, amount),
    onSuccess: (p) => {
      qc.setQueryData(["pool", worldId], p);
      void qc.invalidateQueries({ queryKey: ["studio"] });
    },
  });
  const p = pool.data;
  if (!p) return null;
  const valid = Number.isInteger(amount) && amount >= 1 && amount <= p.max_contribution;

  return (
    <SoftCard className="flex flex-col gap-3" data-testid="pool-card">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-h3">{t("title")}</h2>
        <CoinCounter value={p.balance} />
      </div>
      <p className="text-small text-ink/80">{t("body")}</p>
      {p.recent.length > 0 && (
        <ul className="flex flex-col gap-1 text-small" aria-label={t("recent")}>
          {p.recent.map((g, i) => (
            <li key={`${g.nickname}-${i}`} className="flex justify-between gap-2">
              <Bidi className="font-semibold">{g.nickname}</Bidi>
              <span>{t("gave", { count: g.coins })}</span>
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) give.mutate();
        }}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor={inputId} className="text-small font-semibold">
            {t("amount")}
          </label>
          <input
            id={inputId}
            type="number"
            inputMode="numeric"
            min={1}
            max={p.max_contribution}
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
            className="min-h-11 w-24 rounded-pixel-step border-2 border-ink bg-white px-3"
          />
        </div>
        <PixelButton type="submit" variant="spend" disabled={!valid || give.isPending}>
          {t("give")}
        </PixelButton>
      </form>
      <p className="text-small text-ink/70">{t("note", { max: p.max_contribution })}</p>
      <ErrorBanner error={give.error} />
    </SoftCard>
  );
}
