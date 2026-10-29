import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, type TutorAction, type TutorSession } from "@/api/client";
import { Banner, Bidi, Chip, MathText, PixelButton, SoftCard, Sprite } from "@/components";
import { cx } from "@/components/cx";
import { JOB_POLL_MS, isTerminal, useJob } from "@/hooks/useJob";
import { ErrorBanner } from "@/features/worlds/parts";

/** …/tutor/new?chapter&level — opens a session (the first question is a job), then the chat. */
export function TutorStartPage() {
  const { worldId = "", courseId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const start = useMutation({
    mutationFn: () =>
      api.tutorStart(params.get("chapter") ?? "", params.get("level") ?? "intermediate"),
    onSuccess: (r) =>
      void navigate(`/worlds/${worldId}/courses/${courseId}/tutor/${r.session_id}`, {
        replace: true,
      }),
  });
  const { mutate } = start;
  useEffect(() => mutate(), [mutate]);
  return (
    <main className="p-8">
      <ErrorBanner error={start.error} />
    </main>
  );
}

/** …/tutor/:sessionId — the Socratic Tutor (mockup 14). It asks; it never hands over the answer. */
export function TutorPage() {
  const { worldId = "", courseId = "", sessionId = "" } = useParams();
  const { t } = useTranslation("tutor");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const inputId = useId();
  const bottom = useRef<HTMLDivElement>(null);

  const query = useQuery({
    queryKey: ["tutor", sessionId],
    queryFn: () => api.tutorSession(sessionId),
    refetchInterval: (q) => (q.state.data?.pending_job_id ? JOB_POLL_MS : false),
  });
  const session = query.data;
  const pending = useJob(session?.pending_job_id ?? null);
  const jobDone = isTerminal(pending.status);
  useEffect(() => {
    if (jobDone) void qc.invalidateQueries({ queryKey: ["tutor", sessionId] });
  }, [jobDone, qc, sessionId]);
  useEffect(() => bottom.current?.scrollIntoView?.({ block: "end" }), [session?.turns.length]);

  const send = useMutation({
    mutationFn: ({ msg, action }: { msg: string; action: TutorAction }) =>
      api.tutorTurn(sessionId, msg, action),
    onSuccess: () => {
      setText("");
      void qc.invalidateQueries({ queryKey: ["tutor", sessionId] });
    },
  });
  const end = useMutation({
    mutationFn: () => api.tutorEnd(sessionId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["tutor", sessionId] }),
  });

  if (!session)
    return (
      <main className="p-8">
        <ErrorBanner error={query.error} />
      </main>
    );
  const island = `/worlds/${worldId}/courses/${courseId}`;
  const busy = !!session.pending_job_id || send.isPending;
  const quick = session.turns.some((x) => x.quick_mode);
  const act = (action: TutorAction, msg = "") => send.mutate({ msg, action });

  return (
    <div className="flex min-h-screen flex-col bg-whitewash">
      <header className="flex flex-wrap items-center gap-3 border-b-2 border-sand px-4 py-3 sm:px-8">
        <Sprite name="tutorCafe" scale={2} />
        <div className="min-w-0">
          <p className="font-semibold">{t("common:buildings.socratic_tutor")}</p>
          <p className="text-small text-ink/70">
            <Bidi>{session.course_name}</Bidi> · <Bidi>{session.chapter_title}</Bidi>
          </p>
        </div>
        {quick && <Chip kind="quickMode">{t("quickMode")}</Chip>}
        <div className="ms-auto">
          {session.status === "active" ? (
            <PixelButton
              variant="secondary"
              disabled={busy || end.isPending}
              onClick={() => end.mutate()}
            >
              {t("end")}
            </PixelButton>
          ) : (
            <Link to={island} className="font-semibold text-primary underline">
              {t("backIsland")}
            </Link>
          )}
        </div>
      </header>

      <div className="grid flex-1 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <main className="flex min-w-0 flex-col">
          <ol className="flex flex-1 flex-col gap-4 px-4 py-6 sm:px-8" aria-live="polite">
            {session.turns.map((turn, k) =>
              turn.role === "student" ? (
                <li key={k} className="flex justify-end">
                  <p
                    className="max-w-xl rounded-pixel-step border-2 border-primary-dark bg-primary px-4 py-3 text-white"
                    dir="auto"
                  >
                    {turn.text ? (
                      <MathText text={turn.text} />
                    ) : (
                      t(`actions.${turn.action ?? "message"}`)
                    )}
                  </p>
                </li>
              ) : (
                <li key={k} className="flex items-start gap-3">
                  <Sprite name="tutorCafe" scale={1} alt={t("common:buildings.socratic_tutor")} />
                  <div className="flex max-w-xl flex-col gap-1">
                    <p
                      className="rounded-pixel-step border-2 border-ink bg-white px-4 py-3"
                      dir="auto"
                    >
                      <MathText text={turn.text} />
                    </p>
                    <div className="flex flex-wrap gap-2 text-small text-ink/70">
                      {turn.tier === "mid" && <span>{t("deeper")}</span>}
                      {turn.quick_mode && <Chip kind="quickMode">{t("quickMode")}</Chip>}
                      {turn.confidence === "low" && <span>{t("askTeacher")}</span>}
                    </div>
                  </div>
                </li>
              ),
            )}
            {busy && session.status === "active" && (
              <li className="flex flex-col gap-2">
                {pending.queuePosition !== null && pending.status === "queued" && (
                  <Banner kind="queue">
                    {t("common:jobs.queue", {
                      position: pending.queuePosition,
                      seconds: pending.etaS ?? 0,
                    })}
                  </Banner>
                )}
                <p className="flex items-center gap-2 text-ink/70" role="status">
                  <Sprite name="tutorCafe" scale={1} />
                  {pending.job?.stage
                    ? t(`common:loading.stages.${pending.job.stage}`)
                    : t("thinking")}
                  …
                </p>
              </li>
            )}
            {pending.status === "failed" && pending.job?.error && (
              <li>
                <Banner kind="error">{t(`common:${pending.job.error}`)}</Banner>
              </li>
            )}
            <div ref={bottom} />
          </ol>

          {session.status === "active" ? (
            <div className="sticky bottom-0 flex flex-col gap-3 border-t-2 border-sand bg-whitewash px-4 py-4 sm:px-8">
              <div className="flex flex-wrap gap-2">
                <PixelButton
                  variant="secondary"
                  disabled={busy || session.hints_used >= session.max_hints}
                  onClick={() => act("hint")}
                >
                  {t("hint", { used: session.hints_used, max: session.max_hints })}
                </PixelButton>
                <PixelButton variant="secondary" disabled={busy} onClick={() => act("another_way")}>
                  {t("anotherWay")}
                </PixelButton>
              </div>
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (text.trim()) act("message", text.trim());
                }}
              >
                <label htmlFor={inputId} className="sr-only">
                  {t("placeholder")}
                </label>
                <textarea
                  id={inputId}
                  dir="auto"
                  rows={2}
                  value={text}
                  maxLength={1500}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={t("placeholder")}
                  className="min-h-14 min-w-0 flex-1 rounded-pixel-step border-2 border-ink bg-white px-3 py-2"
                />
                <PixelButton variant="spend" disabled={busy} onClick={() => act("stuck")}>
                  {t("stuck")}
                </PixelButton>
                <PixelButton type="submit" disabled={busy || !text.trim()}>
                  {t("send")}
                </PixelButton>
              </form>
              <ErrorBanner error={send.error ?? end.error} />
            </div>
          ) : (
            session.summary && <Summary session={session} island={island} navigate={navigate} />
          )}
        </main>
        <GoalPanel session={session} />
      </div>
    </div>
  );
}

function GoalPanel({ session }: { session: TutorSession }) {
  const { t } = useTranslation("tutor");
  return (
    <aside className="flex flex-col gap-5 border-sand bg-sand/20 p-5 lg:border-s-2">
      <div>
        <p className="text-small font-semibold uppercase tracking-wider text-terracotta-ink">
          {t("goal")}
        </p>
        <p className="font-heading text-h3" dir="auto">
          {session.goal ? <MathText text={session.goal} /> : "…"}
        </p>
      </div>
      <div className="flex flex-col gap-2">
        <div className="flex justify-between text-small font-semibold">
          <span>{t("hintsUsed")}</span>
          <span>{t("hintsCount", { used: session.hints_used, max: session.max_hints })}</span>
        </div>
        <ol className="flex gap-1" aria-hidden>
          {Array.from({ length: session.max_hints }, (_, k) => (
            <li
              key={k}
              className={cx(
                "h-3 flex-1 rounded-pixel-step border-2 border-ink",
                k < session.hints_used ? "bg-terracotta" : "bg-sand",
              )}
            />
          ))}
        </ol>
      </div>
      <div className="flex flex-col gap-2">
        <p className="font-semibold">{t("ideas")}</p>
        <ul className="flex flex-col gap-2">
          {session.ideas.map((idea) => (
            <li key={idea.text} className="flex items-start gap-2">
              <span
                aria-label={idea.found ? t("found") : t("notYet")}
                role="img"
                className={cx(
                  "mt-1 h-4 w-4 shrink-0 rounded-pixel-step",
                  idea.found ? "bg-olive-ink" : "bg-sand",
                )}
              />
              <span className={idea.found ? "" : "text-ink/60"} dir="auto">
                <MathText text={idea.text} />
              </span>
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-auto text-small text-ink/70">{t("note")}</p>
    </aside>
  );
}

function Summary({
  session,
  island,
  navigate,
}: {
  session: TutorSession;
  island: string;
  navigate: (to: string) => void;
}) {
  const { t } = useTranslation("tutor");
  const s = session.summary as { summary?: string; next_step?: string; ideas_found?: string[] };
  return (
    <SoftCard className="mx-4 mb-6 flex flex-col gap-3 sm:mx-8">
      <h2 className="text-h2">{t("summary.title")}</h2>
      <p dir="auto">
        <MathText text={s.summary ?? ""} />
      </p>
      {s.ideas_found && s.ideas_found.length > 0 && (
        <p className="text-small">{t("summary.found", { count: s.ideas_found.length })}</p>
      )}
      <p className="font-semibold" dir="auto">
        {t("summary.next")} <MathText text={s.next_step ?? ""} />
      </p>
      <div className="flex flex-wrap gap-3">
        <PixelButton
          onClick={() =>
            navigate(`${island}/quiz/new?chapter=${session.chapter_id}&level=${session.level}`)
          }
        >
          {t("summary.quiz")}
        </PixelButton>
        <PixelButton variant="secondary" onClick={() => navigate(island)}>
          {t("backIsland")}
        </PixelButton>
      </div>
    </SoftCard>
  );
}
