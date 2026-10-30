import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type StudioPay } from "@/api/client";
import { Bidi, PixelButton, PixelPanel, Sprite } from "@/components";
import { cx } from "@/components/cx";
import { JobProgress } from "@/features/jobs/JobProgress";
import { useWisdomTip } from "@/features/wisdom/useWisdomTip";
import { ErrorBanner } from "@/features/worlds/parts";
import { useOnce } from "@/hooks/useOnce";
import { cardsKey } from "./cards";
import { GeneratePanel } from "./GeneratePanel";
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
          cost={s.cost}
          poolBalance={s.pool_balance}
          title={t("make.title")}
          body={t("make.body")}
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
