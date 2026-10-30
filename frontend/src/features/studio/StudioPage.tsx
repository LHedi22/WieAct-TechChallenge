import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type Studio, type StudioPay } from "@/api/client";
import { Banner, Bidi, Chip, PixelButton, PixelPanel, Sprite } from "@/components";
import { cx } from "@/components/cx";
import { useNumberFormat } from "@/components/useNumberFormat";
import { JobProgress } from "@/features/jobs/JobProgress";
import { PoolCard } from "@/features/pool/PoolCard";
import { useWisdomTip } from "@/features/wisdom/useWisdomTip";
import { ErrorBanner } from "@/features/worlds/parts";
import { useOnce } from "@/hooks/useOnce";
import { useWallet } from "@/hooks/useSession";
import { cardsKey } from "./cards";
import { Flashcards } from "./Flashcards";
import { MindMapView, NotesView } from "./StudyViews";

const TABS = ["notes", "flashcards", "map"] as const;
type Tab = (typeof TABS)[number];

/** …/studio?chapter&level&tab — Study Studio (mockup 16 + DESIGN.md fix 14: notes and mind map
 * tabs). One study pack per chapter + level + language, made once for the whole class: free when
 * it exists, otherwise generated (paid by the student or the Class Pool) behind a loading screen.
 * Calm study screen: no top bar, no mascot. */
export function StudioPage() {
  const { worldId = "", courseId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const chapterId = params.get("chapter") ?? "";
  const level = params.get("level") ?? "intermediate";
  const tab: Tab = (TABS as readonly string[]).includes(params.get("tab") ?? "")
    ? (params.get("tab") as Tab)
    : "notes";
  const { t } = useTranslation("studio");
  const { t: tc } = useTranslation();
  const qc = useQueryClient();
  const island = useQuery({ queryKey: ["island", courseId], queryFn: () => api.island(courseId) });
  const studio = useQuery({
    queryKey: ["studio", chapterId, level],
    queryFn: () => api.studio(chapterId, level),
    enabled: !!chapterId,
  });
  const s = studio.data;
  const chapter = island.data?.chapters.find((c) => c.id === chapterId);
  const tip = useWisdomTip(worldId, courseId);

  // The job on screen: one this student started, or a classmate's already running (shared, free).
  const [started, setStarted] = useState<string | null>(null);
  const [finished, setFinished] = useState<string[]>([]);
  const pending = s?.pending_job_id;
  const jobId = started ?? (pending && !finished.includes(pending) ? pending : null);
  const generate = useMutation({
    mutationFn: (pay: StudioPay) => api.studioGenerate(chapterId, level, pay),
    onSuccess: (g) => {
      if (g.job_id) setStarted(g.job_id);
      void qc.invalidateQueries({ queryKey: ["pool", worldId] });
    },
  });
  const onDone = (id: string) => {
    setFinished((f) => [...f, id]);
    setStarted(null);
    void qc.invalidateQueries({ queryKey: ["studio", chapterId, level] });
    void qc.invalidateQueries({ queryKey: cardsKey(chapterId, level) });
  };

  const tabIds = useId();
  const island_ = `/worlds/${worldId}/courses/${courseId}`;
  const missing = s?.missing ?? [];
  const hasCards = (s?.cards.total ?? 0) > 0;

  let body: ReactNode = null;
  if (s) {
    if (jobId) {
      body = (
        <JobProgress jobId={jobId} tip={tip}>
          {(_, job) => <Finish onDone={() => onDone(job.id)} />}
        </JobProgress>
      );
    } else if (tab === "flashcards" && hasCards) {
      body = <Flashcards chapterId={chapterId} level={level} />;
    } else if (missing.includes("notes")) {
      body = (
        <GeneratePanel
          studio={s}
          worldId={worldId}
          busy={generate.isPending}
          onGenerate={(pay) => generate.mutate(pay)}
        />
      );
    } else if (missing.includes(tab)) {
      body = (
        <PixelPanel className="flex flex-col items-start gap-3">
          <p>{t("partMissing")}</p>
          <PixelButton disabled={generate.isPending} onClick={() => generate.mutate("me")}>
            {t("retryFree")}
          </PixelButton>
        </PixelPanel>
      );
    } else if (tab === "notes" && s.notes) {
      body = <NotesView notes={s.notes} />;
    } else if (tab === "map" && s.map) {
      body = <MindMapView map={s.map} />;
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-whitewash">
      <header className="border-b-2 border-ink bg-sand/30">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 px-4 pt-4">
          <div className="flex items-center gap-3">
            <Sprite name="studyStudio" scale={2} />
            <div>
              <h1 className="text-h3">{tc("buildings.study_studio")}</h1>
              <p className="text-small text-ink/70">
                <Bidi>{island.data?.name}</Bidi>
                {chapter && (
                  <>
                    {" · "}
                    {t("chapter", { n: chapter.idx })} · <Bidi>{chapter.title}</Bidi>
                  </>
                )}{" "}
                · {tc(`chip.${level}`)}
              </p>
            </div>
          </div>
          <Link
            to={island_}
            className="inline-flex min-h-11 items-center rounded-pixel-step border-2 border-ink bg-white px-4 font-semibold shadow-lip"
          >
            {t("back")}
          </Link>
        </div>
        <div
          role="tablist"
          aria-label={tc("buildings.study_studio")}
          className="mx-auto mt-3 flex w-full max-w-5xl gap-1 overflow-x-auto px-4"
        >
          {TABS.map((k) => (
            <button
              key={k}
              type="button"
              role="tab"
              id={`${tabIds}-${k}`}
              aria-selected={tab === k}
              aria-controls={`${tabIds}-panel`}
              onClick={() => setParams((p) => (p.set("tab", k), p), { replace: true })}
              className={cx(
                "-mb-0.5 min-h-11 shrink-0 rounded-t-pixel-step border-2 px-3 font-semibold sm:px-4",
                tab === k
                  ? "border-ink border-b-whitewash bg-whitewash"
                  : "border-transparent text-ink/70",
              )}
            >
              {t(`tabs.${k}`)}
            </button>
          ))}
        </div>
      </header>
      <main
        id={`${tabIds}-panel`}
        role="tabpanel"
        aria-labelledby={`${tabIds}-${tab}`}
        className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6"
      >
        <ErrorBanner error={studio.error ?? generate.error} />
        {body}
      </main>
    </div>
  );
}

function Finish({ onDone }: { onDone: () => void }) {
  useOnce(onDone);
  return null;
}

/** No pack yet for this chapter + level + language: what it costs, who pays, and the pool. */
function GeneratePanel({
  studio,
  worldId,
  busy,
  onGenerate,
}: {
  studio: Studio;
  worldId: string;
  busy: boolean;
  onGenerate: (pay: StudioPay) => void;
}) {
  const { t } = useTranslation("studio");
  const { t: tc } = useTranslation();
  const nf = useNumberFormat();
  const coins = useWallet().data?.coins ?? 0;
  const poolOk = studio.pool_balance >= studio.cost;
  const [pay, setPay] = useState<StudioPay>(poolOk && coins < studio.cost ? "pool" : "me");
  const name = useId();
  const after = pay === "me" ? coins - studio.cost : studio.pool_balance - studio.cost;

  return (
    <div className="flex flex-col gap-4">
      <PixelPanel className="flex flex-col gap-4" data-testid="generate-panel">
        <h2 className="text-h2">{t("make.title")}</h2>
        <p>{t("make.body")}</p>
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
                  : t("make.pool", { count: studio.pool_balance })}
              </span>
            </label>
          ))}
        </fieldset>
        <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1">
          <dt>{t("make.cost")}</dt>
          <dd className="text-end">
            <Chip kind="cost">{tc("chip.cost", { count: studio.cost })}</Chip>
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
