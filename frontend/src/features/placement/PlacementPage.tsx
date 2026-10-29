import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { api, type PlacementQuestion, type PlacementResult } from "@/api/client";
import { Bidi, Chip, Mascot, PixelButton, PixelPanel, ProgressBar, SoftCard } from "@/components";
import { cx } from "@/components/cx";
import { JobProgress } from "@/features/jobs/JobProgress";
import { ErrorBanner } from "@/features/worlds/parts";

type Level = "beginner" | "intermediate" | "advanced";

/** /worlds/:worldId/courses/:courseId/placement — 8 free questions that set the course level.
 * A calm study screen: no water, no mascot until the result. */
export function PlacementPage() {
  const { worldId = "", courseId = "" } = useParams();
  const { t } = useTranslation("placement");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [questions, setQuestions] = useState<PlacementQuestion[] | null>(null);
  const [answers, setAnswers] = useState<(number | null)[]>([]);
  const [i, setI] = useState(0);
  const receive = useCallback((qs: PlacementQuestion[]) => {
    setQuestions(qs);
    setAnswers(qs.map(() => null));
  }, []);

  const start = useMutation({
    mutationFn: () => api.placementStart(courseId),
    onSuccess: (s) => s.questions && receive(s.questions),
  });
  const { mutate } = start;
  useEffect(() => mutate(), [mutate]);

  const finish = useMutation({
    mutationFn: () => api.placementFinish(courseId, answers),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["island", courseId] });
      void qc.invalidateQueries({ queryKey: ["map", worldId] });
    },
  });

  const island = `/worlds/${worldId}/courses/${courseId}`;

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 bg-whitewash px-4 py-8">
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-h2">{t("title")}</h1>
        <button
          type="button"
          onClick={() => void navigate(island)}
          className="font-semibold text-primary underline"
        >
          {t("leave")}
        </button>
      </header>
      <ErrorBanner error={start.error ?? finish.error} />

      {!questions && start.data?.job_id && (
        <JobProgress jobId={start.data.job_id}>
          {() => <QuestionsLoader courseId={courseId} onReady={receive} />}
        </JobProgress>
      )}

      {questions && !finish.data && (
        <Question
          q={questions[i]!}
          n={i + 1}
          total={questions.length}
          picked={answers[i] ?? null}
          onPick={(a) => setAnswers((xs) => xs.map((x, j) => (j === i ? a : x)))}
          onBack={i > 0 ? () => setI(i - 1) : undefined}
          onNext={() => (i + 1 < questions.length ? setI(i + 1) : finish.mutate())}
          finishing={finish.isPending}
        />
      )}

      {finish.data && <Result result={finish.data} onDone={() => void navigate(island)} />}
    </main>
  );
}

function QuestionsLoader({
  courseId,
  onReady,
}: {
  courseId: string;
  onReady: (q: PlacementQuestion[]) => void;
}) {
  const q = useQuery({
    queryKey: ["placement", courseId],
    queryFn: () => api.placementQuestions(courseId),
  });
  useEffect(() => {
    if (q.data) onReady(q.data.questions);
  }, [q.data, onReady]);
  return <ErrorBanner error={q.error} />;
}

function Question({
  q,
  n,
  total,
  picked,
  onPick,
  onBack,
  onNext,
  finishing,
}: {
  q: PlacementQuestion;
  n: number;
  total: number;
  picked: number | null;
  onPick: (a: number) => void;
  onBack?: () => void;
  onNext: () => void;
  finishing: boolean;
}) {
  const { t } = useTranslation("placement");
  const { t: tc } = useTranslation();
  return (
    <section className="flex flex-col gap-5" aria-labelledby={`q-${q.i}`}>
      <ProgressBar value={n} max={total} label={tc("progress.questionOf", { n, total })} />
      <h2 id={`q-${q.i}`} className="text-h3" dir="auto">
        {q.question}
      </h2>
      <fieldset className="flex flex-col gap-3">
        <legend className="sr-only">{t("options")}</legend>
        {q.options.map((opt, k) => (
          <label
            key={k}
            className={cx(
              "flex min-h-12 cursor-pointer items-center gap-3 rounded-pixel-step border-2 bg-white px-4 py-3",
              picked === k ? "border-primary bg-primary/5" : "border-sand",
            )}
          >
            <input
              type="radio"
              name={`q-${q.i}`}
              checked={picked === k}
              onChange={() => onPick(k)}
              className="h-5 w-5 accent-primary"
            />
            <span dir="auto">{opt}</span>
          </label>
        ))}
      </fieldset>
      <p className="text-small text-ink/70">{t("noPressure")}</p>
      <div className="flex justify-between gap-3">
        {onBack ? (
          <PixelButton variant="secondary" onClick={onBack}>
            {t("back")}
          </PixelButton>
        ) : (
          <span />
        )}
        <PixelButton onClick={onNext} disabled={finishing}>
          {n < total ? t("next") : t("finish")}
        </PixelButton>
      </div>
    </section>
  );
}

function Result({ result, onDone }: { result: PlacementResult; onDone: () => void }) {
  const { t } = useTranslation("placement");
  const { t: tc } = useTranslation();
  const level = result.level as Level;
  return (
    <PixelPanel className="flex flex-col items-center gap-4 p-6 text-center">
      <Mascot pose="celebrating" scale={3} />
      <h2 className="text-h2">{t("result.title")}</h2>
      <Chip kind={level}>{tc(`chip.${level}`)}</Chip>
      <p>{t(`result.${level}`)}</p>
      <p className="text-small text-ink/70">
        <Bidi>{t("result.score", { correct: result.correct, total: result.total })}</Bidi>
      </p>
      <ul className="flex w-full flex-col gap-2 text-start">
        {result.chapters.map((c) => (
          <li key={c.chapter_id}>
            <SoftCard className="flex items-center justify-between p-3">
              <Bidi className="font-semibold">{c.title}</Bidi>
              <span className="text-small">
                {t("result.chapter", { correct: c.correct, asked: c.asked })}
              </span>
            </SoftCard>
          </li>
        ))}
      </ul>
      <PixelButton variant="spend" onClick={onDone}>
        {t("result.toIsland")}
      </PixelButton>
    </PixelPanel>
  );
}
