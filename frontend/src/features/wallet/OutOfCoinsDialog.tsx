import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type Product } from "@/api/client";
import { useUiStore } from "@/app/uiStore";
import { Banner, Bidi, Mascot, PixelButton, PixelPanel, SoftCard, Sprite } from "@/components";
import { useNumberFormat } from "@/components/useNumberFormat";
import { useEconomy, useWallet } from "@/hooks/useSession";

/** "You're out of coins for today" (mockup 17, with DESIGN.md fixes 4–6): refill countdown, free
 * ways to earn, and the demo top-ups. Opened by any 402 from a paid start. Every number comes from
 * /api/economy and /api/wallet. */
export function OutOfCoinsDialog() {
  const open = useUiStore((s) => s.outOfCoins);
  const close = useUiStore((s) => s.setOutOfCoins);
  return open ? <Dialog onClose={() => close(false)} /> : null;
}

function useCountdown(iso: string | undefined) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  const s = iso ? Math.max(0, Math.round((Date.parse(iso) - now) / 1000)) : 0;
  return { h: Math.floor(s / 3600), m: Math.floor((s % 3600) / 60), fraction: 1 - s / 86_400 };
}

function Dialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("wallet");
  const { t: tc } = useTranslation();
  const nf = useNumberFormat();
  const eco = useEconomy().data;
  const wallet = useWallet().data;
  const qc = useQueryClient();
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const left = useCountdown(wallet?.refill_at);
  const buy = useMutation({
    mutationFn: (product: Product) => api.demoPurchase(product),
    onSuccess: (r) => qc.setQueryData(["wallet"], r.wallet),
  });

  useEffect(() => {
    panel.current?.querySelector<HTMLElement>("button")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!eco) return null;
  const pack = eco.products.coin_pack;
  const pass = eco.products.exam_pass;
  const quizCost = eco.cost.quiz ?? 0;
  const quizzes = quizCost > 0 ? Math.floor(pack.coins / quizCost) : 0;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center overflow-y-auto p-4">
      <button
        type="button"
        aria-label={t("close")}
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 bg-ink/40"
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative my-auto w-full max-w-3xl"
      >
        <PixelPanel className="flex flex-col gap-5">
          <div className="flex items-start gap-4">
            <div className="hidden shrink-0 sm:block">
              <Mascot pose="waving" scale={4} />
            </div>
            <div className="flex flex-1 flex-col gap-2">
              <h2 id={titleId} className="text-h1">
                {t("title")}
              </h2>
              <p>{t("body")}</p>
              <div className="flex items-center gap-3">
                <Sprite name="hourglass" scale={2} />
                <p>
                  <span className="block text-small text-ink/70">
                    {t("refill", { count: eco.daily_free_coins })}
                  </span>
                  <span className="font-heading text-h2">
                    <Bidi>{tc("counters.duration", { h: left.h, m: left.m })}</Bidi>
                  </span>
                </p>
              </div>
            </div>
            <PixelButton variant="secondary" onClick={onClose} aria-label={t("close")}>
              ✕
            </PixelButton>
          </div>

          {buy.isSuccess && (
            <Banner kind="placement">
              {t("bought", { coins: nf.format(buy.data.wallet.coins) })}
            </Banner>
          )}
          {buy.isError && <Banner kind="error">{tc("errors.try_again")}</Banner>}

          <div className="grid gap-5 md:grid-cols-2">
            <section className="flex flex-col gap-2">
              <h3 className="text-h3">{t("earnTitle")}</h3>
              <SoftCard className="flex items-center gap-3">
                <Sprite name="teachBackArena" scale={1} />
                <span className="flex-1">
                  {t("earnAnswer", { score: eco.peer_answer_threshold })}
                </span>
                <span className="font-semibold text-terracotta-ink">
                  {t("perAnswer", { count: eco.earn.peer_answer_good })}
                </span>
              </SoftCard>
              <p className="text-small text-ink/70">
                {t("earnCap", { count: eco.daily_earn_cap })}
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h3 className="text-h3">{t("topUpTitle")}</h3>
              <div className="grid gap-3 sm:grid-cols-2">
                <SoftCard className="flex flex-col gap-2">
                  <span className="flex items-center gap-2 font-semibold">
                    <Sprite name="chest" scale={1} /> {t("pack.name")}
                  </span>
                  <span className="text-small">
                    {t("pack.gives", { coins: pack.coins, quizzes })}
                  </span>
                  <PixelButton
                    variant="secondary"
                    disabled={buy.isPending}
                    onClick={() => buy.mutate("coin_pack")}
                  >
                    {t("demoBuy", { price: pack.price_tnd })}
                  </PixelButton>
                </SoftCard>
                <SoftCard className="flex flex-col gap-2 !border-terracotta">
                  <span className="flex items-center gap-2 font-semibold">
                    <Sprite name="star" scale={1} /> {t("pass.name")}
                  </span>
                  <span className="text-small">
                    {t("pass.gives", { days: pass.days, count: eco.exam_pass_daily_limit })}
                  </span>
                  <PixelButton
                    variant="spend"
                    disabled={buy.isPending}
                    onClick={() => buy.mutate("exam_pass")}
                  >
                    {t("demoBuy", { price: pass.price_tnd })}
                  </PixelButton>
                </SoftCard>
              </div>
              <p className="text-small text-ink/70">{t("demoNote")}</p>
            </section>
          </div>

          <p className="flex items-center gap-2 rounded-pixel-step bg-olive-light/30 p-3 text-small">
            <span aria-hidden="true">✓</span>
            {t("savedFree")}
          </p>
        </PixelPanel>
      </div>
    </div>
  );
}
