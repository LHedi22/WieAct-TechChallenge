import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type MapCourse, type MapOut } from "@/api/client";
import { TopBar } from "@/app/TopBar";
import {
  Avatar,
  type AvatarLook,
  Bidi,
  Chip,
  Mascot,
  MasteryRing,
  PixelButton,
  PixelPanel,
  SoftCard,
  Sprite,
  WaterTile,
} from "@/components";
import { cx } from "@/components/cx";
import { ErrorBanner } from "@/features/worlds/parts";
import { accentOf } from "./layout";
import { MapScene, type Zoom } from "./MapScene";
import { LeaderboardCard } from "@/features/leaderboard/Leaderboard";
import { ChallengesCard } from "@/features/daily/Challenges";
import { useDaily } from "@/features/daily/useDaily";

type View = "map" | "list";

/** /worlds/:worldId — the archipelago (mockup 06), list view, or "still all sea" (mockup 10). */
export function MapPage() {
  const { worldId = "" } = useParams();
  const { t } = useTranslation("map");
  const navigate = useNavigate();
  const [view, setView] = useState<View>(() =>
    typeof window !== "undefined" && window.innerWidth < 640 ? "list" : "map",
  );
  const [zoom, setZoom] = useState<Zoom>(1);
  const query = useQuery({ queryKey: ["map", worldId], queryFn: () => api.worldMap(worldId) });
  const data = query.data;
  const daily = useDaily().data;
  const welcomeBack = Boolean(daily?.first_open_today && daily.returning);
  useEffect(() => {
    if (welcomeBack) void navigate(`/worlds/${worldId}/today`, { replace: true });
  }, [welcomeBack, navigate, worldId]);

  const open = (c: MapCourse) => void navigate(`/worlds/${worldId}/courses/${c.id}`);
  const place = (c: MapCourse) => void navigate(`/worlds/${worldId}/courses/${c.id}/placement`);

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar worldId={worldId} />
      <ErrorBanner error={query.error} />
      {data && (
        <div className="grid flex-1 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <main className="relative min-w-0">
            {data.courses.every((c) => !c.ready) ? (
              <EmptyWorld data={data} />
            ) : (
              <>
                <h1 className="sr-only">{t("title", { name: data.name })}</h1>
                {view === "map" ? (
                  <MapScene
                    courses={data.courses}
                    zoom={zoom}
                    onOpen={open}
                    onPlacement={place}
                    className="h-[calc(100vh-4.5rem)] rounded-none"
                  />
                ) : (
                  <ListView data={data} onOpen={open} onPlacement={place} />
                )}
                <div className="pointer-events-none absolute inset-x-3 bottom-3 flex flex-wrap items-end justify-between gap-2">
                  <div className="pointer-events-auto flex gap-2">
                    <div
                      role="group"
                      aria-label={t("view.label")}
                      className="flex rounded-pixel-step border-2 border-ink bg-white"
                    >
                      {(["map", "list"] as const).map((v) => (
                        <button
                          key={v}
                          type="button"
                          aria-pressed={view === v}
                          onClick={() => setView(v)}
                          className={cx(
                            "min-h-11 px-4 font-semibold",
                            view === v && "bg-primary text-white",
                          )}
                        >
                          {t(`view.${v}`)}
                        </button>
                      ))}
                    </div>
                    {view === "map" && (
                      <div
                        role="group"
                        aria-label={t("zoom.label")}
                        className="flex rounded-pixel-step border-2 border-ink bg-white"
                      >
                        <button
                          type="button"
                          aria-label={t("zoom.in")}
                          disabled={zoom === 3}
                          onClick={() => setZoom((z) => Math.min(3, z + 1) as Zoom)}
                          className="min-h-11 min-w-11 font-semibold disabled:opacity-40"
                        >
                          +
                        </button>
                        <button
                          type="button"
                          aria-label={t("zoom.out")}
                          disabled={zoom === 1}
                          onClick={() => setZoom((z) => Math.max(1, z - 1) as Zoom)}
                          className="min-h-11 min-w-11 font-semibold disabled:opacity-40"
                        >
                          −
                        </button>
                      </div>
                    )}
                  </div>
                  {view === "map" && (
                    <p className="pointer-events-auto hidden items-center gap-2 rounded-pixel-step border-2 border-ink bg-white px-3 py-2 font-semibold sm:flex">
                      <Sprite name="boat" scale={1} />
                      {t("hint")}
                    </p>
                  )}
                </div>
              </>
            )}
          </main>
          <ClassPanel data={data} />
        </div>
      )}
    </div>
  );
}

function ListView({
  data,
  onOpen,
  onPlacement,
}: {
  data: MapOut;
  onOpen: (c: MapCourse) => void;
  onPlacement: (c: MapCourse) => void;
}) {
  const { t } = useTranslation("map");
  const { t: tc } = useTranslation();
  return (
    <ul className="flex flex-col gap-3 p-4 pb-24 sm:p-6">
      {data.courses.map((c) => {
        const locked = c.ready && c.level === null;
        return (
          <li key={c.id}>
            <SoftCard className="flex flex-wrap items-center gap-4">
              {c.ready && !locked ? (
                <MasteryRing value={c.mastery / 100} accent={accentOf(c.color_key)} />
              ) : (
                <Sprite name={locked ? "lock" : "water"} scale={2} />
              )}
              <div className="min-w-0 flex-1">
                <h2 className="text-h3">
                  <Bidi>{c.name}</Bidi>
                </h2>
                <p className="text-small text-ink/70">
                  {t("list.chapters", { count: c.chapters })} ·{" "}
                  {!c.ready
                    ? t("island.rising")
                    : locked
                      ? t("island.waitingPlacement")
                      : t("island.mastery", { percent: c.mastery })}
                </p>
              </div>
              {c.level && (
                <Chip kind={c.level as "beginner" | "intermediate" | "advanced"}>
                  {tc(`chip.${c.level}`)}
                </Chip>
              )}
              {locked ? (
                <PixelButton variant="spend" onClick={() => onPlacement(c)}>
                  {t("island.startPlacement")}
                </PixelButton>
              ) : (
                <PixelButton disabled={!c.ready} onClick={() => onOpen(c)}>
                  {t("list.open")}
                </PixelButton>
              )}
            </SoftCard>
          </li>
        );
      })}
    </ul>
  );
}

function ClassPanel({ data }: { data: MapOut }) {
  const { t } = useTranslation("map");
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(data.join_code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* the code stays visible to copy by hand */
    }
  };
  return (
    <aside className="flex flex-col gap-4 border-sand bg-whitewash p-4 lg:border-s-2">
      <ChallengesCard />
      <h2 className="text-h2">{t("class.title")}</h2>
      <ul
        className="flex flex-col gap-2"
        aria-label={t("class.members", { count: data.members.length })}
      >
        {data.members.map((m) => (
          <li
            key={m.nickname}
            className={cx(
              "flex items-center gap-3 rounded-soft px-2 py-1",
              m.is_me && "bg-sand/50",
            )}
          >
            <Avatar look={m.avatar as AvatarLook | null} size={36} />
            <Bidi className="font-semibold">{m.nickname}</Bidi>
            {m.is_me && <span className="text-ink/70">{t("class.you")}</span>}
          </li>
        ))}
      </ul>
      <PixelPanel className="flex flex-col gap-2 text-center">
        <p className="text-small font-semibold text-ink/70">{t("class.code")}</p>
        <p dir="ltr" className="font-heading text-h2 tracking-[0.15em]" data-testid="class-code">
          {data.join_code}
        </p>
        <PixelButton variant="secondary" onClick={() => void copy()}>
          {copied ? t("class.copied") : t("class.copy")}
        </PixelButton>
      </PixelPanel>
      <Link to={`/worlds/${data.world_id}/upload`} className="font-semibold text-primary underline">
        {t("class.addMaterial")}
      </Link>
      <LeaderboardCard worldId={data.world_id} />
    </aside>
  );
}

function EmptyWorld({ data }: { data: MapOut }) {
  const { t } = useTranslation("map");
  const navigate = useNavigate();
  const others = data.members.filter((m) => !m.is_me);
  return (
    <WaterTile className="flex min-h-[70vh] items-center justify-center p-4">
      <PixelPanel className="flex max-w-xl flex-col items-center gap-4 p-6 text-center">
        <Mascot pose="waving" scale={4} />
        <h1 className="text-h1">{t("empty.title")}</h1>
        <p className="text-ink/80">
          {data.is_creator
            ? t("empty.bodyCreator", { world: data.name })
            : t("empty.body", { creator: data.creator, world: data.name })}
        </p>
        <ol className="flex flex-wrap justify-center gap-x-5 gap-y-2 text-small">
          {(["step1", "step2", "step3"] as const).map((s, i) => (
            <li key={s} className="flex items-center gap-2">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-pixel-step bg-sand font-semibold">
                {i + 1}
              </span>
              {t(`empty.${s}`)}
            </li>
          ))}
        </ol>
        <PixelButton
          variant="spend"
          onClick={() => void navigate(`/worlds/${data.world_id}/upload`)}
        >
          {t("empty.upload")}
        </PixelButton>
        <p className="flex flex-wrap items-center justify-center gap-2 text-small text-ink/70">
          {others.slice(0, 4).map((m) => (
            <Avatar key={m.nickname} look={m.avatar as AvatarLook | null} size={28} />
          ))}
          <span>
            {t("empty.waiting", { count: others.length })} · {t("empty.code")}{" "}
            <bdi dir="ltr" className="font-semibold tracking-wider">
              {data.join_code}
            </bdi>
          </span>
        </p>
      </PixelPanel>
    </WaterTile>
  );
}
