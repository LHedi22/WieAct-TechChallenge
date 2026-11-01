import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { DailyChallenge } from "@/api/client";
import { Banner, Bidi, Chip, ProgressBar, SoftCard } from "@/components";
import { cx } from "@/components/cx";
import { useEconomy } from "@/hooks/useSession";
import { useDaily } from "./useDaily";

function target(c: DailyChallenge): string | null {
  if (!c.world_id || !c.course_id) return null;
  const island = `/worlds/${c.world_id}/courses/${c.course_id}`;
  if (c.type === "teachback" && c.chapter_id) return `${island}/arena?chapter=${c.chapter_id}`;
  return island;
}

function ChallengeRow({ c }: { c: DailyChallenge }) {
  const { t } = useTranslation("daily");
  const economy = useEconomy().data;
  const label = t(`type.${c.type}`, { count: c.target, percent: c.target, chapter: c.chapter });
  const link = target(c);
  const where = c.chapter && c.type !== "quiz_score" ? `${c.course} · ${c.chapter}` : c.course;
  return (
    <li>
      <SoftCard className={cx("flex flex-col gap-2 p-3", c.done && "border-olive-light")}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-semibold">
              {c.done && <span className="sr-only">{t("done")} </span>}
              {label}
            </p>
            {where && (
              <p className="truncate text-small text-ink/70">
                <Bidi>{where}</Bidi>
              </p>
            )}
          </div>
          {economy && (
            <span className="shrink-0 text-small font-semibold text-terracotta-ink">
              {t("reward", {
                coins: economy.earn.daily_challenge,
                points: economy.points.daily_challenge,
              })}
            </span>
          )}
        </div>
        {c.why && <p className="text-small text-ink/80">{c.why}</p>}
        <ProgressBar
          value={c.type === "quiz_score" ? Math.min(c.progress, c.target) : c.progress}
          max={c.target}
          label={label}
        />
        {c.done ? (
          <Chip kind="confidence" className="self-start">
            {t("done")}
          </Chip>
        ) : (
          link && (
            <Link to={link} className="self-start text-small font-semibold text-primary underline">
              {t("go")}
            </Link>
          )
        )}
      </SoftCard>
    </li>
  );
}

/** The 3 challenges of today, progress, rewards from /api/economy, and the all-done bonus. */
export function ChallengeList({ challenges }: { challenges: DailyChallenge[] }) {
  return (
    <ol className="flex flex-col gap-2">
      {challenges.map((c, i) => (
        <ChallengeRow key={`${c.type}-${i}`} c={c} />
      ))}
    </ol>
  );
}

/** Side panel on the map (mockup 06): today's challenges + the in-app study reminder. */
export function ChallengesCard() {
  const { t } = useTranslation("daily");
  const economy = useEconomy().data;
  const daily = useDaily().data;
  if (!daily) return null;
  return (
    <section className="flex flex-col gap-2" aria-labelledby="daily-card" data-testid="daily-card">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="daily-card" className="text-h3">
          {t("title")}
        </h2>
        <span className="text-small text-ink/70">
          {daily.planned_by === "ai" ? t("plannedForYou") : t("planning")}
        </span>
      </div>
      {daily.reminder_due && <Banner kind="placement">{t("reminder")}</Banner>}
      {daily.message && <p className="text-small text-ink/80">{daily.message}</p>}
      <ChallengeList challenges={daily.challenges} />
      {daily.all_done && economy && (
        <p className="text-small font-semibold text-olive-ink">
          {t("allDone", { points: economy.points.all_challenges_bonus })}
        </p>
      )}
    </section>
  );
}
