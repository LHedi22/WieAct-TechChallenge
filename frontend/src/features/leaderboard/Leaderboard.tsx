import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { api, type LeaderboardEntry } from "@/api/client";
import { TopBar } from "@/app/TopBar";
import { Avatar, type AvatarLook, Bidi, PixelButton, SoftCard } from "@/components";
import { cx } from "@/components/cx";
import { useNumberFormat } from "@/components/useNumberFormat";
import { ErrorBanner } from "@/features/worlds/parts";

type Scope = "world" | "global";
type Period = "week" | "all";

function Row({ e }: { e: LeaderboardEntry }) {
  const { t } = useTranslation("leaderboard");
  const nf = useNumberFormat();
  return (
    <li
      className={cx(
        "flex items-center gap-3 rounded-soft px-2 py-1",
        e.is_me && "bg-sand/50 font-semibold",
      )}
    >
      <span className="w-6 text-end tabular-nums text-ink/70">
        <Bidi>{nf.format(e.rank)}</Bidi>
      </span>
      <Avatar look={e.avatar as AvatarLook | null} size={32} />
      <span className="flex-1 truncate">
        {e.nickname ? <Bidi>{e.nickname}</Bidi> : <span className="italic">{t("hidden")}</span>}
        {e.is_me && <span className="ms-1 text-ink/70">{t("you")}</span>}
      </span>
      <span className="tabular-nums">
        <Bidi>{nf.format(e.points)}</Bidi>
      </span>
    </li>
  );
}

/** Side panel on the map: this week in the class, top 5 + you. */
export function LeaderboardCard({ worldId }: { worldId: string }) {
  const { t } = useTranslation("leaderboard");
  const board = useQuery({
    queryKey: ["leaderboard", "world", "week", worldId],
    queryFn: () => api.leaderboard("world", "week", worldId),
    refetchInterval: 30_000,
  }).data;
  if (!board) return null;
  const top = board.entries.slice(0, 5);
  const meOutside = board.me && !top.some((e) => e.is_me);
  return (
    <section className="flex flex-col gap-2" aria-labelledby="lb-card">
      <h2 id="lb-card" className="text-h3">
        {t("cardTitle")}
      </h2>
      {top.length === 0 ? (
        <p className="text-small text-ink/70">{t("empty")}</p>
      ) : (
        <ol className="flex flex-col gap-1">
          {top.map((e) => (
            <Row key={e.rank} e={e} />
          ))}
          {meOutside && board.me && <Row e={board.me} />}
        </ol>
      )}
      <Link
        to={`/worlds/${worldId}/leaderboard`}
        className="text-small font-semibold text-primary underline"
      >
        {t("seeAll")}
      </Link>
    </section>
  );
}

/** /worlds/:worldId/leaderboard — class or global, this week or all time, with the opt-out. */
export function LeaderboardPage() {
  const { worldId = "" } = useParams();
  const { t } = useTranslation("leaderboard");
  const qc = useQueryClient();
  const [scope, setScope] = useState<Scope>("world");
  const [period, setPeriod] = useState<Period>("week");
  const board = useQuery({
    queryKey: ["leaderboard", scope, period, worldId],
    queryFn: () => api.leaderboard(scope, period, scope === "world" ? worldId : undefined),
  });
  const optIn = useMutation({
    mutationFn: (on: boolean) => api.saveProfile({ leaderboard_opt_in: on }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["leaderboard"] }),
  });
  const data = board.data;

  const tab = <T extends string>(value: T, current: T, set: (v: T) => void, label: string) => (
    <button
      key={value}
      type="button"
      role="tab"
      aria-selected={value === current}
      onClick={() => set(value)}
      className={cx(
        "min-h-11 rounded-pixel-step border-2 px-4 font-semibold",
        value === current ? "border-ink bg-primary text-white" : "border-sand bg-white",
      )}
    >
      {label}
    </button>
  );

  return (
    <div className="min-h-screen bg-whitewash">
      <TopBar worldId={worldId} />
      <main className="mx-auto flex max-w-2xl flex-col gap-4 p-4 sm:p-8">
        <Link to={`/worlds/${worldId}`} className="font-semibold text-primary underline">
          {t("back")}
        </Link>
        <h1 className="text-h1">{t("title")}</h1>
        <div className="flex flex-wrap gap-2" role="tablist" aria-label={t("scopeLabel")}>
          {tab("world", scope, setScope, t("scope.world"))}
          {tab("global", scope, setScope, t("scope.global"))}
        </div>
        <div className="flex flex-wrap gap-2" role="tablist" aria-label={t("periodLabel")}>
          {tab("week", period, setPeriod, t("period.week"))}
          {tab("all", period, setPeriod, t("period.all"))}
        </div>
        <ErrorBanner error={board.error ?? optIn.error} />
        {data && (
          <SoftCard className="flex flex-col gap-3">
            {data.entries.length === 0 ? (
              <p className="text-ink/70">{t("empty")}</p>
            ) : (
              <ol className="flex flex-col gap-1">
                {data.entries.map((e) => (
                  <Row key={e.rank} e={e} />
                ))}
                {data.me && !data.entries.some((e) => e.is_me) && <Row e={data.me} />}
              </ol>
            )}
            <div className="flex flex-wrap items-center gap-3 border-t-2 border-sand pt-3">
              <p className="flex-1 text-small">{data.opted_in ? t("visible") : t("hiddenSelf")}</p>
              <PixelButton
                variant="secondary"
                disabled={optIn.isPending}
                onClick={() => optIn.mutate(!data.opted_in)}
              >
                {data.opted_in ? t("hideMe") : t("showMe")}
              </PixelButton>
            </div>
          </SoftCard>
        )}
      </main>
    </div>
  );
}
