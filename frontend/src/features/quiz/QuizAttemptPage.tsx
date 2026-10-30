import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type QuizAttempt, type QuizQuestion, type QuizResults } from "@/api/client";
import {
  Bidi,
  Chip,
  MathText,
  PixelButton,
  PixelPanel,
  SegmentedProgress,
  type SegmentState,
  SoftCard,
  Sprite,
} from "@/components";
import { cx } from "@/components/cx";
import { ErrorBanner } from "@/features/worlds/parts";

const LETTERS = ["A", "B", "C", "D"];
const OVER = new Set(["correct", "second", "wrong", "skipped"]);

function segment(q: QuizQuestion, current: boolean): SegmentState {
  if (q.status === "correct" || q.status === "second") return "correct";
  if (q.status === "wrong" || q.status === "skipped") return "wrong";
  return current ? "current" : "pending";
}

/** …/quiz/:attemptId — one question per screen; hint and a second try before the answer (mockup 12). */
export function QuizAttemptPage() {
  const { worldId = "", courseId = "", attemptId = "" } = useParams();
  const { t } = useTranslation("quiz");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ["attempt", attemptId],
    queryFn: () => api.quizAttempt(attemptId),
  });
  const attempt = query.data;
  const [shown, setShown] = useState<number | null>(null);
  const [results, setResults] = useState<QuizResults | null>(null);

  const finish = useMutation({
    mutationFn: () => api.quizFinish(attemptId),
    onSuccess: (r) => {
      setResults(r);
      void qc.invalidateQueries({ queryKey: ["island", courseId] });
    },
  });
  const { mutate: finishNow } = finish;
  useEffect(() => {
    if (attempt?.status === "finished" && !results) finishNow(); // reopened: show the results
  }, [attempt?.status, results, finishNow]);

  const island = `/worlds/${worldId}/courses/${courseId}`;
  if (results && attempt) return <Results attempt={attempt} results={results} island={island} />;
  if (!attempt)
    return (
      <main className="p-8">
        <ErrorBanner error={query.error} />
      </main>
    );

  const i = shown ?? Math.min(attempt.current, attempt.questions.length - 1);
  const q = attempt.questions[i]!;
  const update = (nq: QuizQuestion) => {
    setShown(nq.i); // stay on this question (hint / explanation) until the student taps Next
    qc.setQueryData<QuizAttempt>(["attempt", attemptId], (a) =>
      a
        ? {
            ...a,
            questions: a.questions.map((x) => (x.i === nq.i ? nq : x)),
            current: nextOpen(a, nq),
          }
        : a,
    );
  };

  return (
    <div className="flex min-h-screen flex-col bg-whitewash">
      <QuizHeader attempt={attempt} n={i + 1}>
        <PixelButton variant="secondary" onClick={() => void navigate(island)}>
          {t("saveExit")}
        </PixelButton>
      </QuizHeader>
      <SegmentedProgress
        className="mx-auto w-full max-w-3xl px-4 pt-4"
        segments={attempt.questions.map((x) => segment(x, x.i === i))}
      />
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6">
        <Question
          key={q.i}
          attemptId={attemptId}
          q={q}
          onUpdate={update}
          onNext={() => {
            const next = attempt.questions.find((x) => x.i > q.i && !OVER.has(x.status));
            const any = next ?? attempt.questions.find((x) => !OVER.has(x.status) && x.i !== q.i);
            if (any) setShown(any.i);
            else finish.mutate();
          }}
          last={attempt.questions.filter((x) => !OVER.has(x.status)).length === 0}
        />
        <ErrorBanner error={finish.error} />
      </main>
    </div>
  );
}

function nextOpen(a: QuizAttempt, nq: QuizQuestion): number {
  const qs = a.questions.map((x) => (x.i === nq.i ? nq : x));
  const open = qs.find((x) => !OVER.has(x.status));
  return open ? open.i : qs.length;
}

function QuizHeader({
  attempt,
  n,
  children,
}: {
  attempt: QuizAttempt;
  n?: number;
  children?: React.ReactNode;
}) {
  const { t } = useTranslation("quiz");
  return (
    <header className="flex flex-wrap items-center gap-4 border-b-2 border-sand px-4 py-3 sm:px-8">
      <Sprite name="quizHall" scale={2} />
      <div className="min-w-0">
        <p className="font-semibold">{t("common:buildings.quiz_hall")}</p>
        <p className="text-small text-ink/70">
          <Bidi>{attempt.course_name}</Bidi> · <Bidi>{attempt.chapter_title}</Bidi> ·{" "}
          {t(`common:chip.${attempt.level}`)}
        </p>
      </div>
      {n !== undefined && (
        <p className="mx-auto text-small font-semibold">
          {t("common:progress.questionOf", { n, total: attempt.questions.length })}
        </p>
      )}
      <div className="ms-auto">{children}</div>
    </header>
  );
}

function Question({
  attemptId,
  q,
  onUpdate,
  onNext,
  last,
}: {
  attemptId: string;
  q: QuizQuestion;
  onUpdate: (q: QuizQuestion) => void;
  onNext: () => void;
  last: boolean;
}) {
  const { t } = useTranslation("quiz");
  const [choice, setChoice] = useState<number | null>(null);
  const answer = useMutation({
    mutationFn: (c: number) => api.quizAnswer(attemptId, q.i, c),
    onSuccess: (nq) => {
      setChoice(null);
      onUpdate(nq);
    },
  });
  const skip = useMutation({ mutationFn: () => api.quizSkip(attemptId, q.i), onSuccess: onUpdate });
  const over = OVER.has(q.status);
  const yours = q.second ?? q.first;

  const optionState = (k: number) => {
    if (over && k === q.answer_index) return "right";
    if (over && k === yours && q.status !== "correct" && q.status !== "second") return "wrong";
    if (q.status === "hint" && k === q.first) return "wrong";
    return choice === k ? "picked" : "idle";
  };

  return (
    <section className="flex flex-col gap-4" aria-labelledby={`q${q.i}`}>
      <h1 id={`q${q.i}`} className="text-h2" dir="auto">
        <MathText text={q.question} />
      </h1>
      <ul className="flex flex-col gap-3">
        {q.options.map((opt, k) => {
          const state = optionState(k);
          const locked = over || (q.status === "hint" && k === q.first) || answer.isPending;
          return (
            <li key={k}>
              <button
                type="button"
                disabled={locked}
                aria-pressed={choice === k}
                onClick={() => setChoice(k)}
                className={cx(
                  "flex w-full items-center gap-3 rounded-pixel-step border-2 bg-white px-4 py-3 text-start",
                  state === "right" && "border-olive-ink bg-olive-light/20",
                  state === "wrong" && "border-danger bg-danger/5",
                  state === "picked" && "border-primary bg-primary/5",
                  state === "idle" && "border-sand",
                )}
              >
                <span
                  className={cx(
                    "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-pixel-step font-semibold",
                    state === "wrong"
                      ? "bg-danger text-white"
                      : state === "right"
                        ? "bg-olive-ink text-white"
                        : "bg-sand",
                  )}
                >
                  {LETTERS[k]}
                </span>
                <span className="flex-1" dir="auto">
                  <MathText text={opt} />
                </span>
                {state === "wrong" && (
                  <span className="text-small font-semibold text-danger">{t("yourAnswer")}</span>
                )}
                {state === "right" && (
                  <span className="text-small font-semibold text-olive-ink">
                    {t("rightAnswer")}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>

      {q.status === "hint" && (
        <>
          <div role="status" className="rounded-pixel-step border-2 border-danger bg-danger/5 p-4">
            <p className="font-semibold text-danger">{t("notQuite")}</p>
          </div>
          <div className="flex gap-3 rounded-pixel-step border-2 border-sand-dark bg-sand/40 p-4">
            <Sprite name="lantern" scale={2} alt={t("common:icons.lantern")} />
            <div>
              <p className="font-semibold">{t("hint")}</p>
              <p dir="auto">
                <MathText text={q.hint ?? ""} />
              </p>
            </div>
          </div>
        </>
      )}
      {over && (
        <SoftCard
          className={cx(
            q.status === "correct" || q.status === "second"
              ? "border-olive-light"
              : "border-danger/40",
          )}
        >
          <p className="font-semibold">{t(`result.${q.status}`)}</p>
          {q.explanation && (
            <p className="mt-1" dir="auto">
              <MathText text={q.explanation} />
            </p>
          )}
        </SoftCard>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {!over ? (
          <>
            <PixelButton
              disabled={choice === null || answer.isPending}
              onClick={() => choice !== null && answer.mutate(choice)}
            >
              {q.status === "hint" ? t("tryAgain") : t("check")}
            </PixelButton>
            <button
              type="button"
              onClick={() => skip.mutate()}
              disabled={skip.isPending}
              className="ms-auto font-semibold text-primary underline"
            >
              {t("skip")}
            </button>
          </>
        ) : (
          <PixelButton onClick={onNext}>{last ? t("seeResults") : t("next")}</PixelButton>
        )}
      </div>
      {q.status === "hint" && <p className="text-small text-ink/70">{t("hintsFree")}</p>}
      <ErrorBanner error={answer.error ?? skip.error} />
    </section>
  );
}

function Results({
  attempt,
  results,
  island,
}: {
  attempt: QuizAttempt;
  results: QuizResults;
  island: string;
}) {
  const { t } = useTranslation("quiz");
  const { t: tc } = useTranslation();
  const ns = results.next_step;
  const base = island;
  const next =
    ns.kind === "tutor"
      ? `${base}/tutor/new?chapter=${ns.chapter_id}&level=${ns.level}`
      : `${base}/quiz/new?chapter=${ns.chapter_id}&level=${ns.level}`;
  return (
    <div className="flex min-h-screen flex-col bg-whitewash">
      <QuizHeader attempt={attempt} />
      <main className="mx-auto grid w-full max-w-screen-xl gap-6 px-4 py-6 sm:px-8 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <section className="flex flex-col gap-4">
          <PixelPanel className="flex items-center gap-4">
            <div className="rounded-pixel-step border-2 border-ink px-4 py-2 text-center">
              <p className="text-small text-ink/70">{t("results.score")}</p>
              <p className="font-heading text-h1" dir="ltr">
                {results.score}
                <span className="text-h3">/{results.total}</span>
              </p>
            </div>
            <Sprite name="trophy" scale={3} alt={tc("icons.trophy")} />
          </PixelPanel>
          <SoftCard className="flex items-center gap-3">
            <Sprite name="star" scale={2} alt={tc("icons.star")} />
            <p>
              <span className="font-heading text-h2 text-primary">
                +{results.points + results.activity_points}
              </span>{" "}
              {tc("counters.points", { count: results.points + results.activity_points })}
              <span className="block text-small text-ink/70">
                {t("results.pointsSplit", {
                  answers: results.points,
                  bonus: results.activity_points,
                })}
              </span>
            </p>
          </SoftCard>
          <SoftCard className="flex items-center justify-between">
            <span>{t("results.mastery", { title: attempt.chapter_title })}</span>
            {results.weak ? (
              <Chip kind="weakSpot">{tc("chip.weakSpot")}</Chip>
            ) : (
              <span className="font-semibold">{results.mastery}%</span>
            )}
          </SoftCard>
          <PixelPanel className="flex flex-col gap-3">
            <p className="text-small font-semibold uppercase tracking-wider text-terracotta-ink">
              {t("results.nextStep")}
            </p>
            <p>
              {ns.kind === "tutor"
                ? t("results.nextTutor", { title: ns.chapter_title })
                : t("results.nextQuiz", { title: ns.chapter_title, level: tc(`chip.${ns.level}`) })}
            </p>
            <Link
              to={next}
              className="inline-flex min-h-11 items-center gap-2 self-start rounded-pixel-step bg-terracotta-ink px-4 font-semibold text-white shadow-lip"
            >
              {ns.kind === "tutor" ? t("results.goTutor") : t("results.goQuiz")}
              <Chip kind="cost">{tc("chip.cost", { count: ns.cost })}</Chip>
            </Link>
            <Link to={island} className="self-start font-semibold text-primary underline">
              {t("results.backIsland")}
            </Link>
          </PixelPanel>
        </section>
        <section className="flex flex-col gap-3">
          <h1 className="text-h2">{t("results.lookAgain", { count: results.missed.length })}</h1>
          <ul className="flex flex-col gap-3">
            {results.missed.map((m) => (
              <li key={m.i}>
                <SoftCard className="flex gap-3">
                  <span className="inline-flex h-8 min-w-10 items-center justify-center rounded-pixel-step bg-danger/10 font-semibold text-danger">
                    {t("results.q", { n: m.i + 1 })}
                  </span>
                  <div className="min-w-0 flex-1" dir="auto">
                    <p className="font-semibold">
                      <MathText text={m.question} />
                    </p>
                    <p className="text-small text-ink/80">
                      {m.yours ? `${t("results.yours")} ` : t("results.skipped")}
                      {m.yours && <MathText text={m.yours} />} · {t("results.correct")}{" "}
                      <MathText text={m.correct} />
                      {m.status === "second" && ` · ${t("results.half")}`}
                    </p>
                    {m.explanation && (
                      <p className="mt-1 text-small">
                        <MathText text={m.explanation} />
                      </p>
                    )}
                  </div>
                </SoftCard>
              </li>
            ))}
          </ul>
          {results.right_concepts.length > 0 && (
            <SoftCard className="border-olive-light bg-olive-light/10 text-small">
              {t("results.rightConcepts", {
                count: results.total - results.missed.length,
                list: results.right_concepts.join(", "),
              })}
            </SoftCard>
          )}
        </section>
      </main>
    </div>
  );
}
