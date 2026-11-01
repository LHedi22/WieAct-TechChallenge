import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { TopBar } from "@/app/TopBar";
import { CoinCounter, PixelButton, PixelPanel, StreakCounter } from "@/components";
import { ErrorBanner } from "@/features/worlds/parts";
import { useEconomy } from "@/hooks/useSession";
import { ChallengeList } from "./Challenges";
import { useDaily } from "./useDaily";

/** /worlds/:worldId/today — the first open of a day (PRODUCT.md screen 12): refilled coins,
 * streak, the 3 challenges → map. */
export function DailyReturnPage() {
  const { worldId = "" } = useParams();
  const { t } = useTranslation("daily");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const economy = useEconomy().data;
  const daily = useDaily();
  const seen = useMutation({
    mutationFn: api.dailySeen,
    onSuccess: (d) => {
      qc.setQueryData(["daily"], d);
      void navigate(`/worlds/${worldId}`, { replace: true });
    },
  });
  const d = daily.data;

  return (
    <div className="flex min-h-screen flex-col bg-whitewash">
      <TopBar worldId={worldId} />
      <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-8">
        <h1 className="text-h1">{t("welcome")}</h1>
        <ErrorBanner error={daily.error ?? seen.error} />
        {d && (
          <>
            <PixelPanel className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <div className="flex items-center gap-2">
                <CoinCounter value={d.coins} />
                <span>{t("refilled", { count: economy?.daily_free_coins ?? d.free_today })}</span>
              </div>
              <div className="flex items-center gap-2">
                <StreakCounter days={d.streak} />
              </div>
            </PixelPanel>
            <section className="flex flex-col gap-3" aria-labelledby="today">
              <h2 id="today" className="text-h2">
                {t("today")}
              </h2>
              {d.message && <p className="text-ink/80">{d.message}</p>}
              <ChallengeList challenges={d.challenges} />
              {economy && (
                <p className="text-small text-ink/70">
                  {t("bonusHint", { points: economy.points.all_challenges_bonus })}
                </p>
              )}
            </section>
            <PixelButton
              className="self-start"
              onClick={() => seen.mutate()}
              disabled={seen.isPending}
            >
              {t("continue")}
            </PixelButton>
          </>
        )}
      </main>
    </div>
  );
}
