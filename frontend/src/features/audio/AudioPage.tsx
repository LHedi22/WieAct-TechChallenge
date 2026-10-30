import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type StudioPay } from "@/api/client";
import { Bidi, Sprite } from "@/components";
import { JobProgress } from "@/features/jobs/JobProgress";
import { GeneratePanel } from "@/features/studio/GeneratePanel";
import { useWisdomTip } from "@/features/wisdom/useWisdomTip";
import { ErrorBanner } from "@/features/worlds/parts";
import { useOnce } from "@/hooks/useOnce";
import { Player } from "./Player";

/** …/audio?chapter&level — Audio Studio (DESIGN.md fix 14): a short spoken revision episode,
 * written once for the class and read aloud by the browser's own speech engine (no audio leaves
 * or reaches our servers). Darija, or a browser without a voice for the language: transcript only. */
export function AudioPage() {
  const { worldId = "", courseId = "" } = useParams();
  const [params] = useSearchParams();
  const chapterId = params.get("chapter") ?? "";
  const level = params.get("level") ?? "intermediate";
  const { t, i18n } = useTranslation("audio");
  const { t: tc } = useTranslation();
  const qc = useQueryClient();
  const island = useQuery({ queryKey: ["island", courseId], queryFn: () => api.island(courseId) });
  const episode = useQuery({
    queryKey: ["audio", chapterId, level],
    queryFn: () => api.audio(chapterId, level),
    enabled: !!chapterId,
  });
  const e = episode.data;
  const chapter = island.data?.chapters.find((c) => c.id === chapterId);
  const tip = useWisdomTip(worldId, courseId);

  const [started, setStarted] = useState<string | null>(null);
  const [finished, setFinished] = useState<string[]>([]);
  const pending = e?.pending_job_id;
  const jobId = started ?? (pending && !finished.includes(pending) ? pending : null);
  const generate = useMutation({
    mutationFn: (pay: StudioPay) => api.audioGenerate(chapterId, level, pay),
    onSuccess: (g) => {
      if (g.job_id) setStarted(g.job_id);
      void qc.invalidateQueries({ queryKey: ["pool", worldId] });
    },
  });
  const onDone = (id: string) => {
    setFinished((f) => [...f, id]);
    setStarted(null);
    void qc.invalidateQueries({ queryKey: ["audio", chapterId, level] });
  };
  const headingId = useId();

  let body: ReactNode = null;
  if (e) {
    if (jobId) {
      body = (
        <JobProgress jobId={jobId} tip={tip}>
          {(_, job) => <Finish onDone={() => onDone(job.id)} />}
        </JobProgress>
      );
    } else if (e.script) {
      body = <Player script={e.script} language={e.language || i18n.language} />;
    } else {
      body = (
        <GeneratePanel
          cost={e.cost}
          poolBalance={e.pool_balance}
          title={t("make.title")}
          body={t("make.body")}
          worldId={worldId}
          busy={generate.isPending}
          onGenerate={(pay) => generate.mutate(pay)}
        />
      );
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-whitewash">
      <header className="border-b-2 border-ink bg-sand/30">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 p-4">
          <div className="flex items-center gap-3">
            <Sprite name="audioStudio" scale={2} />
            <div>
              <h1 id={headingId} className="text-h3">
                {tc("buildings.audio_studio")}
              </h1>
              <p className="text-small text-ink/70">
                <Bidi>{island.data?.name}</Bidi>
                {chapter && (
                  <>
                    {" · "}
                    {t("studio:chapter", { n: chapter.idx })} · <Bidi>{chapter.title}</Bidi>
                  </>
                )}{" "}
                · {tc(`chip.${level}`)}
              </p>
            </div>
          </div>
          <Link
            to={`/worlds/${worldId}/courses/${courseId}`}
            className="inline-flex min-h-11 items-center rounded-pixel-step border-2 border-ink bg-white px-4 font-semibold shadow-lip"
          >
            {t("studio:back")}
          </Link>
        </div>
      </header>
      <main
        aria-labelledby={headingId}
        className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6"
      >
        <ErrorBanner error={episode.error ?? generate.error} />
        {body}
      </main>
    </div>
  );
}

function Finish({ onDone }: { onDone: () => void }) {
  useOnce(onDone);
  return null;
}
