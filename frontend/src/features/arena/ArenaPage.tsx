import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type ArenaAnswer, type ArenaDetail, type ArenaQuestion } from "@/api/client";
import { Avatar, type AvatarLook, Bidi, Chip, PixelButton, SoftCard, Sprite } from "@/components";
import { cx } from "@/components/cx";
import { JobProgress } from "@/features/jobs/JobProgress";
import { useWisdomTip } from "@/features/wisdom/useWisdomTip";
import { useJob } from "@/hooks/useJob";
import { useOnce } from "@/hooks/useOnce";
import { useAiPaused } from "@/hooks/useAiPaused";
import { ErrorBanner } from "@/features/worlds/parts";
import { useEconomy } from "@/hooks/useSession";
import { type Fix, ScoreCard } from "./ScoreCard";

const POLL_MS = 5_000; // classmates' questions and answers (no WebSockets: polling)

/** …/arena?chapter= — the Teach-Back Arena (mockup 15): the class's peer room and solo mode. */
export function ArenaPage() {
  const { worldId = "", courseId = "" } = useParams();
  const [params] = useSearchParams();
  const chapterId = params.get("chapter") ?? "";
  const { t } = useTranslation("arena");
  const [tab, setTab] = useState<"peer" | "solo">("peer");
  const feed = useQuery({
    queryKey: ["arena", chapterId],
    queryFn: () => api.arenaFeed(chapterId),
    refetchInterval: POLL_MS,
    enabled: !!chapterId,
  });
  const data = feed.data;

  return (
    <div className="min-h-screen bg-whitewash">
      <header className="flex flex-wrap items-center gap-3 border-b-2 border-sand px-4 py-3 sm:px-8">
        <Sprite name="teachBackArena" scale={1} />
        <div className="flex-1">
          <h1 className="font-heading text-h3">{t("title")}</h1>
          {data && (
            <p className="text-small text-ink/70">
              <Bidi>{data.course_name}</Bidi> · <Bidi>{data.chapter_title}</Bidi>
            </p>
          )}
        </div>
        <div
          role="tablist"
          aria-label={t("modes")}
          className="flex rounded-pixel-step border-2 border-ink"
        >
          {(["peer", "solo"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={tab === m}
              onClick={() => setTab(m)}
              className={cx("min-h-11 px-4 font-semibold", tab === m && "bg-primary text-white")}
            >
              {t(`tab.${m}`)}
            </button>
          ))}
        </div>
        <Link
          to={`/worlds/${worldId}/courses/${courseId}`}
          className="min-h-11 content-center rounded-pixel-step border-2 border-ink bg-white px-4 font-semibold"
        >
          {t("leave")}
        </Link>
      </header>
      <ErrorBanner error={feed.error} />
      {data &&
        (tab === "peer" ? (
          <PeerRoom chapterId={chapterId} questions={data.questions} askCost={data.ask_cost} />
        ) : (
          <SoloMode chapterId={chapterId} cost={data.solo_cost} />
        ))}
    </div>
  );
}

// --- peer room -----------------------------------------------------------------------------------
function PeerRoom({
  chapterId,
  questions,
  askCost,
}: {
  chapterId: string;
  questions: ArenaQuestion[];
  askCost: number;
}) {
  const { t } = useTranslation("arena");
  const eco = useEconomy().data;
  const [selected, setSelected] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const current = selected ?? questions.find((q) => q.status === "open")?.id ?? null;

  return (
    <div className="grid gap-6 p-4 sm:p-8 lg:grid-cols-[22rem_1fr]">
      <section className="flex flex-col gap-3" aria-labelledby="arena-feed">
        <h2 id="arena-feed" className="text-h2">
          {t("feedTitle")}
        </h2>
        {eco && (
          <p className="self-start rounded-soft bg-terracotta-light/20 px-2 py-1 text-small font-semibold text-terracotta-ink">
            {t("rewardHint", {
              count: eco.earn.peer_answer_good,
              score: eco.peer_answer_threshold,
            })}
          </p>
        )}
        {questions.length === 0 && <p className="text-ink/70">{t("noQuestions")}</p>}
        <ul className="flex flex-col gap-3">
          {questions.map((q) => (
            <li key={q.id}>
              <button
                type="button"
                aria-current={q.id === current}
                disabled={q.status !== "open"}
                onClick={() => setSelected(q.id)}
                className={cx(
                  "flex w-full flex-col gap-1 rounded-pixel-step border-2 bg-white p-3 text-start",
                  q.id === current ? "border-primary bg-primary/5" : "border-sand",
                  q.status !== "open" && "opacity-80",
                )}
              >
                <span className="font-semibold">
                  <Bidi>{q.text}</Bidi>
                </span>
                <span className="flex items-center gap-2 text-small text-ink/70">
                  <Avatar look={q.author.avatar as AvatarLook | null} size={20} />
                  <Bidi>{q.author.nickname}</Bidi> ·{" "}
                  {q.status === "pending" ? (
                    t("checking")
                  ) : q.status === "rejected" ? (
                    <span className="text-danger">
                      {t(`rejected.${q.reject_reason ?? "other"}`, {
                        defaultValue: t("rejected.other"),
                      })}
                    </span>
                  ) : q.answers === 0 ? (
                    <span className="font-semibold text-terracotta-ink">{t("noAnswers")}</span>
                  ) : (
                    t("answers", { count: q.answers })
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {asking ? (
          <AskForm chapterId={chapterId} cost={askCost} onDone={() => setAsking(false)} />
        ) : (
          <PixelButton variant="secondary" onClick={() => setAsking(true)}>
            {t("ask")}
          </PixelButton>
        )}
      </section>
      <section aria-live="polite">
        {current ? <QuestionView key={current} id={current} /> : <EmptyRoom />}
      </section>
    </div>
  );
}

/** The Class Wisdom tip for this island's loading screens. */
function useCourseTip() {
  const { worldId = "", courseId = "" } = useParams();
  return useWisdomTip(worldId, courseId);
}

function EmptyRoom() {
  const { t } = useTranslation("arena");
  return <p className="text-ink/70">{t("pickQuestion")}</p>;
}

function AskForm({
  chapterId,
  cost,
  onDone,
}: {
  chapterId: string;
  cost: number;
  onDone: () => void;
}) {
  const { t } = useTranslation("arena");
  const paused = useAiPaused();
  const { t: tc } = useTranslation();
  const qc = useQueryClient();
  const id = useId();
  const [text, setText] = useState("");
  const tip = useCourseTip();
  const ask = useMutation({
    mutationFn: () => api.arenaAsk(chapterId, text.trim()),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["arena", chapterId] }),
  });
  if (ask.data) {
    return (
      <SoftCard className="flex flex-col gap-2">
        <JobProgress jobId={ask.data.job_id} tip={tip}>
          {(result) => (
            <QuestionChecked
              ok={result.status === "open"}
              reason={result.reason as string | null}
              onDone={() => {
                void qc.invalidateQueries({ queryKey: ["arena", chapterId] });
                void qc.invalidateQueries({ queryKey: ["wallet"] });
                onDone();
              }}
            />
          )}
        </JobProgress>
      </SoftCard>
    );
  }
  return (
    <SoftCard className="flex flex-col gap-2">
      <label htmlFor={id} className="font-semibold">
        {t("askLabel")}
      </label>
      <textarea
        id={id}
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={300}
        rows={3}
        className="rounded-pixel-step border-2 border-ink p-2"
      />
      <p className="text-small text-ink/70">{t("askHelp")}</p>
      <ErrorBanner error={ask.error} />
      <div className="flex justify-end gap-2">
        <PixelButton variant="secondary" onClick={onDone}>
          {t("cancel")}
        </PixelButton>
        <PixelButton
          variant="spend"
          disabled={paused || text.trim().length < 8 || ask.isPending}
          onClick={() => ask.mutate()}
        >
          {t("askSend")} <Chip kind="cost">{tc("chip.cost", { count: cost })}</Chip>
        </PixelButton>
      </div>
    </SoftCard>
  );
}

function QuestionChecked({
  ok,
  reason,
  onDone,
}: {
  ok: boolean;
  reason: string | null;
  onDone: () => void;
}) {
  const { t } = useTranslation("arena");
  return (
    <div className="flex flex-col gap-2">
      <p className={ok ? "text-olive-ink" : "text-danger"}>
        {ok
          ? t("asked")
          : t(`rejected.${reason ?? "other"}`, { defaultValue: t("rejected.other") }) +
            " " +
            t("refunded")}
      </p>
      <PixelButton variant="secondary" onClick={onDone}>
        {t("ok")}
      </PixelButton>
    </div>
  );
}

function QuestionView({ id }: { id: string }) {
  const { t } = useTranslation("arena");
  const query = useQuery({
    queryKey: ["arena-q", id],
    queryFn: () => api.arenaQuestion(id),
    refetchInterval: POLL_MS,
  });
  const d = query.data;
  const [showOthers, setShowOthers] = useState(false);
  if (!d) return <ErrorBanner error={query.error} />;
  const pinned = d.answers.find((a) => a.pinned);
  const others = d.answers.filter((a) => !a.pinned);

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-h1">
        <Bidi>{d.question.text}</Bidi>
      </h2>
      {d.question.is_mine && d.answers.length === 0 && (
        <p className="text-ink/70">{t("waitingForClass")}</p>
      )}
      {pinned && <PeerAnswer a={pinned} detail={d} />}
      <MyAnswer detail={d} />
      {others.length > 0 &&
        (showOthers || !d.my_answer ? (
          others.map((a) => <PeerAnswer key={a.id} a={a} detail={d} />)
        ) : (
          <PixelButton
            variant="secondary"
            className="self-start"
            onClick={() => setShowOthers(true)}
          >
            {t("seeOthers", { count: others.length })}
          </PixelButton>
        ))}
    </div>
  );
}

function PeerAnswer({ a, detail }: { a: ArenaAnswer; detail: ArenaDetail }) {
  const { t } = useTranslation("arena");
  const { t: tc } = useTranslation();
  const qc = useQueryClient();
  const refresh = () => void qc.invalidateQueries({ queryKey: ["arena-q", detail.question.id] });
  const vote = useMutation({
    mutationFn: () => api.arenaHelpful(a.id, !a.voted),
    onSuccess: refresh,
  });
  const pin = useMutation({ mutationFn: () => api.arenaPin(a.id), onSuccess: refresh });
  return (
    <SoftCard className={cx("flex flex-col gap-2", a.pinned && "!border-olive !bg-olive-light/10")}>
      <div className="flex flex-wrap items-center gap-2">
        {a.pinned && <Chip kind="pinned">{tc("chip.pinned")}</Chip>}
        <Avatar look={a.author.avatar as AvatarLook | null} size={28} />
        <Bidi className="font-semibold">{a.author.nickname}</Bidi>
        <span className="ms-auto font-heading text-h3">
          <Bidi>{a.score ?? "–"}</Bidi>
          <span className="text-small text-ink/70">/100</span>
        </span>
        {a.confidence && (
          <Chip kind="confidence">
            {tc("chip.confidence", { level: tc(`confidence.${a.confidence}`) })}
          </Chip>
        )}
      </div>
      <p className="whitespace-pre-line">
        <Bidi>{a.text}</Bidi>
      </p>
      <div className="flex flex-wrap items-center gap-2 text-small">
        <span className="text-ink/70">{t("helpful", { count: a.helpful })}</span>
        <PixelButton
          variant="secondary"
          aria-pressed={a.voted}
          disabled={vote.isPending}
          onClick={() => vote.mutate()}
        >
          {a.voted ? t("unhelpful") : t("markHelpful")}
        </PixelButton>
        {detail.can_pin && (
          <PixelButton variant="success" disabled={pin.isPending} onClick={() => pin.mutate()}>
            {t("pin")}
          </PixelButton>
        )}
      </div>
      <ErrorBanner error={vote.error ?? pin.error} />
    </SoftCard>
  );
}

function MyAnswer({ detail }: { detail: ArenaDetail }) {
  const { t } = useTranslation("arena");
  const qc = useQueryClient();
  const mine = detail.my_answer;
  const [editing, setEditing] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const qid = detail.question.id;
  const grading = (mine?.status === "grading" ? mine.grading_job_id : null) ?? jobId;
  const job = useJob(grading);
  const tip = useCourseTip();

  if (grading) {
    return (
      <SoftCard className="flex flex-col gap-3">
        <JobProgress jobId={grading} tip={tip}>
          {() => (
            <GradedRefresh
              onShown={() => {
                void qc.invalidateQueries({ queryKey: ["arena-q", qid] });
                void qc.invalidateQueries({ queryKey: ["wallet"] });
                void qc.invalidateQueries({ queryKey: ["leaderboard"] });
                setJobId(null);
              }}
            />
          )}
        </JobProgress>
        {job.status === "failed" && (
          <PixelButton
            variant="secondary"
            className="self-start"
            onClick={() => {
              setJobId(null);
              void qc.invalidateQueries({ queryKey: ["arena-q", qid] });
            }}
          >
            {t("retry")}
          </PixelButton>
        )}
      </SoftCard>
    );
  }
  if (!detail.can_answer && !mine) return null;
  if (!mine || editing || mine.status === "failed") {
    return (
      <AnswerForm
        questionId={qid}
        initial={mine?.text ?? ""}
        improving={!!mine}
        onStarted={(id) => {
          setEditing(false);
          setJobId(id);
        }}
        onCancel={mine && mine.status !== "failed" ? () => setEditing(false) : undefined}
      />
    );
  }
  const fb = mine.feedback;
  return (
    <SoftCard className="flex flex-col gap-3 !border-ink">
      <div className="flex flex-wrap items-center gap-2">
        <Avatar look={mine.author.avatar as AvatarLook | null} size={28} />
        <Bidi className="font-semibold">{mine.author.nickname}</Bidi>
        <span className="text-ink/70">{t("yourAnswer")}</span>
        {mine.pinned && <Chip kind="pinned">{t("pinnedYours")}</Chip>}
        {mine.helpful > 0 && (
          <span className="ms-auto text-small font-semibold text-terracotta-ink">
            {t("helpful", { count: mine.helpful })}
          </span>
        )}
      </div>
      {mine.status === "rejected" ? (
        <p className="text-danger">
          {t(`answerRejected.${mine.reject_flag ?? "other"}`, {
            defaultValue: t("answerRejected.other"),
          })}
        </p>
      ) : (
        mine.score !== null && (
          <ScoreCard
            score={mine.score}
            confidence={mine.confidence}
            text={mine.text}
            errors={fb?.errors ?? []}
            good={fb?.good ?? ""}
            missing={fb?.missing ?? []}
            quickMode={fb?.quick_mode}
          />
        )
      )}
      {mine.score !== null && mine.score < detail.threshold && (
        <p className="text-small text-ink/70">{t("belowThreshold", { score: detail.threshold })}</p>
      )}
      <PixelButton variant="primary" className="self-start" onClick={() => setEditing(true)}>
        {t("improve")}
      </PixelButton>
    </SoftCard>
  );
}

/** Rendered once the grade job is done: refresh the question, wallet and leaderboard. */
function GradedRefresh({ onShown }: { onShown: () => void }) {
  const [run] = useState(() => onShown); // the first callback, so it runs once per result
  useOnce(run);
  return null;
}

function AnswerForm({
  questionId,
  initial,
  improving,
  onStarted,
  onCancel,
}: {
  questionId: string;
  initial: string;
  improving: boolean;
  onStarted: (jobId: string) => void;
  onCancel?: () => void;
}) {
  const { t } = useTranslation("arena");
  const paused = useAiPaused();
  const id = useId();
  const [text, setText] = useState(initial);
  const send = useMutation({
    mutationFn: () => api.arenaAnswer(questionId, text.trim()),
    onSuccess: (r) => onStarted(r.job_id),
  });
  return (
    <SoftCard className="flex flex-col gap-2">
      <label htmlFor={id} className="font-semibold">
        {improving ? t("improveLabel") : t("answerLabel")}
      </label>
      <textarea
        id={id}
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={1500}
        rows={5}
        className="rounded-pixel-step border-2 border-ink p-2"
      />
      <p className="text-small text-ink/70">{t("answerHelp")}</p>
      <ErrorBanner error={send.error} />
      <div className="flex justify-end gap-2">
        {onCancel && (
          <PixelButton variant="secondary" onClick={onCancel}>
            {t("cancel")}
          </PixelButton>
        )}
        <PixelButton
          variant="primary"
          disabled={paused || text.trim().length < 20 || send.isPending}
          onClick={() => send.mutate()}
        >
          {t("answerSend")}
        </PixelButton>
      </div>
    </SoftCard>
  );
}

// --- solo ----------------------------------------------------------------------------------------
function SoloMode({ chapterId, cost }: { chapterId: string; cost: number }) {
  const { t } = useTranslation("arena");
  const paused = useAiPaused();
  const { t: tc } = useTranslation();
  const qc = useQueryClient();
  const conceptId = useId();
  const textId = useId();
  const [concept, setConcept] = useState("");
  const [text, setText] = useState("");
  const tip = useCourseTip();
  const start = useMutation({
    mutationFn: () => api.arenaSolo(chapterId, concept.trim(), text.trim()),
  });

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 p-4 sm:p-8">
      <h2 className="text-h2">{t("solo.title")}</h2>
      <p className="text-ink/70">{t("solo.intro")}</p>
      {start.data ? (
        <SoftCard>
          <JobProgress jobId={start.data.job_id} tip={tip}>
            {(r) => (
              <div className="flex flex-col gap-3">
                <GradedRefresh
                  onShown={() => {
                    void qc.invalidateQueries({ queryKey: ["wallet"] });
                    void qc.invalidateQueries({ queryKey: ["leaderboard"] });
                  }}
                />
                {r.flag !== "ok" || r.score === null ? (
                  <p className="text-danger">
                    {t(`answerRejected.${r.flag as string}`, {
                      defaultValue: t("answerRejected.other"),
                    })}
                  </p>
                ) : (
                  <>
                    <ScoreCard
                      score={r.score as number}
                      confidence={r.confidence as string}
                      text={text}
                      errors={r.errors as Fix[]}
                      good={r.good as string}
                      missing={r.missing as string[]}
                    />
                    <p className="font-semibold text-primary">
                      +{r.points as number} {tc("counters.points", { count: r.points as number })}
                    </p>
                  </>
                )}
                <PixelButton
                  variant="secondary"
                  className="self-start"
                  onClick={() => start.reset()}
                >
                  {t("solo.again")}
                </PixelButton>
              </div>
            )}
          </JobProgress>
        </SoftCard>
      ) : (
        <SoftCard className="flex flex-col gap-3">
          <label htmlFor={conceptId} className="font-semibold">
            {t("solo.concept")}
          </label>
          <input
            id={conceptId}
            value={concept}
            onChange={(e) => setConcept(e.target.value)}
            maxLength={120}
            className="min-h-11 rounded-pixel-step border-2 border-ink px-2"
          />
          <label htmlFor={textId} className="font-semibold">
            {t("solo.explain")}
          </label>
          <textarea
            id={textId}
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={1500}
            rows={6}
            className="rounded-pixel-step border-2 border-ink p-2"
          />
          <ErrorBanner error={start.error} />
          <PixelButton
            variant="spend"
            className="self-end"
            disabled={
              paused || concept.trim().length < 2 || text.trim().length < 20 || start.isPending
            }
            onClick={() => start.mutate()}
          >
            {t("solo.send")} <Chip kind="cost">{tc("chip.cost", { count: cost })}</Chip>
          </PixelButton>
        </SoftCard>
      )}
    </div>
  );
}
