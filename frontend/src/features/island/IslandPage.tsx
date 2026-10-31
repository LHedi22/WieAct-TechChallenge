import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type IslandOut } from "@/api/client";
import { TopBar } from "@/app/TopBar";
import {
  Avatar,
  type AvatarLook,
  Banner,
  Bidi,
  Chip,
  MasteryRing,
  PixelButton,
  SoftCard,
  Sprite,
  type SpriteName,
  WaterTile,
} from "@/components";
import { cx } from "@/components/cx";
import { islandSceneSvg } from "@/components/sprite/art";
import { useCalmMotion } from "@/hooks/useCalmMotion";
import { useMe } from "@/hooks/useSession";
import { ErrorBanner } from "@/features/worlds/parts";
import { BUILDING_POSITIONS, EXPLORER, accentOf } from "@/features/map/layout";
import { BuildingDialog } from "./BuildingDialog";

const SPRITE: Record<string, SpriteName> = {
  quiz_hall: "quizHall",
  socratic_tutor: "tutorCafe",
  study_studio: "studyStudio",
  audio_studio: "audioStudio",
  teachback_arena: "teachBackArena",
};
const PRESENCE_MS = 30_000;

type Building = IslandOut["buildings"][number];

/** /worlds/:worldId/courses/:courseId — the island with its five buildings (mockup 07). */
export function IslandPage() {
  const { worldId = "", courseId = "" } = useParams();
  const { t } = useTranslation("island");
  const { t: tc, i18n } = useTranslation();
  const navigate = useNavigate();
  const me = useMe().data;
  const calm = useCalmMotion();
  // phones: the scene is wider than the screen, so open it scrolled to the middle of the island
  const centre = useCallback((el: HTMLDivElement | null) => {
    if (el) el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2;
  }, []);
  const [picked, setPicked] = useState<Building | null>(null);
  const ground = useMemo(
    () =>
      `data:image/svg+xml,${encodeURIComponent(
        islandSceneSvg(Object.values(BUILDING_POSITIONS), EXPLORER),
      )}`,
    [],
  );
  const query = useQuery({
    queryKey: ["island", courseId],
    queryFn: () => api.island(courseId),
    refetchInterval: PRESENCE_MS, // "on this island now" follows classmates coming and going
  });
  const island = query.data;

  useEffect(() => {
    void api.presence(courseId).catch(() => undefined);
    const id = window.setInterval(
      () => void api.presence(courseId).catch(() => undefined),
      PRESENCE_MS,
    );
    return () => window.clearInterval(id);
  }, [courseId]);

  const placement = `/worlds/${worldId}/courses/${courseId}/placement`;

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar worldId={worldId} />
      <ErrorBanner error={query.error} />
      {island && (
        <div className="grid flex-1 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <main className="relative flex min-w-0 flex-col">
            <div className="z-10 flex flex-wrap items-start gap-3 p-3 lg:absolute lg:inset-x-3 lg:top-3 lg:p-0">
              <Link
                to={`/worlds/${worldId}`}
                className="inline-flex min-h-11 items-center gap-2 rounded-pixel-step border-2 border-ink bg-white px-3 font-semibold shadow-lip"
              >
                <span aria-hidden className="rtl:rotate-180">
                  ←
                </span>
                {t("back")}
              </Link>
              {!island.level && (
                // solid backing: the banner's tint would otherwise sit on the busy island art
                <div className="min-w-0 flex-1 basis-64 rounded-pixel-step bg-white">
                  <Banner
                    kind="placement"
                    action={
                      <PixelButton variant="spend" onClick={() => void navigate(placement)}>
                        {t("placement.start")}
                      </PixelButton>
                    }
                  >
                    <span className="font-semibold">{t("placement.title")}</span>{" "}
                    {t("placement.body")}
                  </Banner>
                </div>
              )}
            </div>
            <div ref={centre} dir="ltr" className="flex-1 overflow-auto">
              <WaterTile className="flex min-h-full items-center lg:pt-16">
                <div
                  dir="ltr"
                  className="relative mx-auto w-full max-w-[1100px]"
                  style={{ minWidth: "720px", aspectRatio: "16 / 11" }}
                  data-testid="island-scene"
                >
                  <img
                    src={ground}
                    alt=""
                    aria-hidden
                    draggable={false}
                    className="pixelated absolute inset-0 h-full w-full"
                  />
                  {island.buildings.map((b) => {
                    const pos = BUILDING_POSITIONS[b.key] ?? { x: 50, y: 50 };
                    return (
                      <button
                        key={b.key}
                        type="button"
                        onClick={() => setPicked(b)}
                        className="group absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-1 rounded-pixel-step focus-visible:outline focus-visible:outline-4 focus-visible:outline-sea"
                        // physical position on purpose: the island is geography, never mirrored
                        style={{ left: `${pos.x}%`, top: `${pos.y}%` }}
                        data-building={b.key}
                      >
                        <Sprite
                          name={SPRITE[b.key] ?? "quizHall"}
                          scale={4}
                          className="transition-transform duration-press group-hover:-translate-y-1"
                        />
                        <span
                          dir={i18n.dir()}
                          className="flex flex-col items-center rounded-pixel-step border-2 border-ink bg-white px-2 py-1 text-small font-semibold shadow-lip group-hover:bg-sand"
                        >
                          {tc(`buildings.${b.key}`)}
                          <CostLabel building={b} />
                        </span>
                      </button>
                    );
                  })}
                  <div
                    aria-hidden
                    className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center"
                    style={{ left: `${EXPLORER.x}%`, top: `${EXPLORER.y}%` }}
                  >
                    <motion.div
                      animate={calm ? undefined : { y: [0, -3, 0] }}
                      transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
                    >
                      <Avatar look={me?.avatar as AvatarLook | null} size={72} bare />
                    </motion.div>
                    <div className="-mt-2 h-2 w-12 rounded-full bg-ink/20" />
                    {me && (
                      <Bidi className="mt-1 rounded-pixel-step border-2 border-ink bg-white px-2 text-small font-semibold">
                        {me.nickname}
                      </Bidi>
                    )}
                  </div>
                  <p className="absolute bottom-1 start-1/2 -translate-x-1/2 rounded-pixel-step border-2 border-ink bg-white px-3 py-2 text-small font-semibold shadow-lip">
                    {t("hint")}
                  </p>
                </div>
              </WaterTile>
            </div>
          </main>
          <IslandPanel island={island} />
        </div>
      )}
      {island && picked && (
        <BuildingDialog
          island={island}
          building={picked}
          onClose={() => setPicked(null)}
          onConfirm={(chapter, level) => {
            const base = `/worlds/${worldId}/courses/${courseId}`;
            const q = `?chapter=${chapter}&level=${level}`;
            const open: Record<string, string> = {
              quiz_hall: `${base}/quiz/new${q}`,
              socratic_tutor: `${base}/tutor/new${q}`,
              teachback_arena: `${base}/arena${q}`,
              study_studio: `${base}/studio${q}`,
              audio_studio: `${base}/audio${q}`,
            };
            const to = open[picked.key];
            if (to) void navigate(to);
          }}
        />
      )}
    </div>
  );
}

function CostLabel({ building }: { building: Building }) {
  const { t } = useTranslation("island");
  const { t: tc } = useTranslation();
  if (building.answer_cost === 0)
    return (
      <span className="text-terracotta-ink">{t("costs.teachback", { ask: building.cost })}</span>
    );
  if (building.cost === 0) return <span className="text-olive-ink">{tc("chip.free")}</span>;
  return (
    <span className="inline-flex items-center gap-1 text-terracotta-ink">
      <Sprite name="coin" scale={1} alt={tc("icons.coin")} />
      {building.free_if_cached ? t("costs.freeIfCached", { cost: building.cost }) : building.cost}
    </span>
  );
}

function IslandPanel({ island }: { island: IslandOut }) {
  const { t } = useTranslation("island");
  const { t: tc } = useTranslation();
  const where = island.visitors[0]?.chapter;
  return (
    <aside className="flex flex-col gap-5 border-sand bg-whitewash p-4 lg:border-s-2">
      <div className="flex items-center gap-3">
        <MasteryRing value={island.mastery / 100} accent={accentOf(island.color_key)} size={56} />
        <div>
          <h1 className="text-h2">
            <Bidi>{island.name}</Bidi>
          </h1>
          <p className="text-small text-ink/70">
            {t("mastery", { percent: island.mastery })} ·{" "}
            {island.level ? tc(`chip.${island.level}`) : t("levelNotSet")}
          </p>
        </div>
      </div>
      <section className="flex flex-col gap-2">
        <h2 className="text-h3">{t("chapters")}</h2>
        <ul className="flex flex-col gap-2">
          {island.chapters.map((c) => (
            <li key={c.id}>
              <SoftCard className="flex flex-col gap-2 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold">
                    {c.idx} · <Bidi>{c.title}</Bidi>
                  </span>
                  {c.weak ? (
                    <Chip kind="weakSpot">{tc("chip.weakSpot")}</Chip>
                  ) : (
                    <span className="text-small text-ink/70">
                      {c.mastery === null ? t("notStarted") : `${c.mastery}%`}
                    </span>
                  )}
                </div>
                <div
                  role="progressbar"
                  aria-label={t("chapterMastery", { title: c.title })}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={c.mastery ?? 0}
                  className="h-3 overflow-hidden rounded-pixel-step border-2 border-ink bg-sand"
                >
                  <div
                    className={cx("h-full", c.weak ? "bg-terracotta" : "bg-primary")}
                    style={{ inlineSize: `${c.mastery ?? 0}%` }}
                  />
                </div>
                {!c.ready && <p className="text-small text-ink/70">{t("noMaterial")}</p>}
              </SoftCard>
            </li>
          ))}
        </ul>
      </section>
      <section className="flex flex-col gap-2">
        <h2 className="text-h3">{t("now.title")}</h2>
        {island.visitors.length ? (
          <div className="flex flex-wrap items-center gap-2">
            {island.visitors.slice(0, 5).map((v) => (
              <Avatar
                key={v.nickname}
                look={v.avatar as AvatarLook | null}
                size={32}
                label={v.nickname}
              />
            ))}
            <p className="text-small text-ink/70">
              {where
                ? t("now.studyingChapter", { count: island.visitors.length, chapter: where })
                : t("now.studying", { count: island.visitors.length })}
            </p>
          </div>
        ) : (
          <p className="text-small text-ink/70">{t("now.nobody")}</p>
        )}
      </section>
      <SoftCard className="mt-auto flex items-start gap-2 border-olive-light bg-olive-light/10 text-small">
        <span aria-hidden>✓</span>
        <span>{t("freeNote")}</span>
      </SoftCard>
    </aside>
  );
}
