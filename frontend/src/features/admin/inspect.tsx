// /admin/debug/students: one student's whole account, checked against the economy rules (backend
// app/admin/inspect.py). Read-only; changes go through the admin actions on the Users page.
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { adminCall } from "./adminApi";
import { useDebug } from "./debugKit";
import type { PriceExplain, Student } from "./debugTypes";
import { KV, Loading, Raw } from "./debugUi";
import { inputClass, plainError, when } from "./format";
import { qs } from "./hooks";
import { DataTable } from "./table";
import type { Page } from "./hooks";
import type { UserRow } from "./types";
import { ErrorNote, Field, Pill, Section, SmallButton } from "./ui";

const ACTIVITIES = [
  "quiz",
  "study_pack",
  "audio",
  "tutor_session",
  "teachback_solo",
  "peer_question",
] as const;
const NEEDS_CHAPTER = new Set(["quiz", "study_pack", "audio"]);

export function StudentSearch() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const res = useQuery({
    queryKey: ["admin", "debug", "student-search", search],
    queryFn: () => adminCall<Page<UserRow>>(`/api/admin/users${qs({ q: search, page: 1 })}`),
    enabled: search !== "",
  });
  return (
    <Section title="Find a student">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSearch(q.trim());
        }}
      >
        <Field label="Nickname">
          <input className={inputClass} value={q} onChange={(e) => setQ(e.target.value)} />
        </Field>
        <SmallButton type="submit">Search</SmallButton>
      </form>
      <p className="mt-2 text-small">
        Or open one from the{" "}
        <Link className="text-primary underline" to="/admin/users">
          Users
        </Link>{" "}
        page.
      </p>
      {search && (
        <div className="mt-3">
          {res.data ? (
            <DataTable
              rows={res.data.items}
              rowKey={(u) => u.id}
              onOpen={(u) => nav(`/admin/debug/students/${u.id}`)}
              columns={[
                {
                  label: "Nickname",
                  render: (u) => <span className="font-semibold">{u.nickname}</span>,
                },
                { label: "Coins", render: (u) => u.wallet.coins },
                { label: "Points", render: (u) => u.points },
              ]}
            />
          ) : (
            <Loading q={res} />
          )}
        </div>
      )}
    </Section>
  );
}

function Fold({
  title,
  raw,
  children,
  open = true,
  badge,
}: {
  title: string;
  raw: unknown;
  children: ReactNode;
  open?: boolean;
  badge?: ReactNode;
}) {
  return (
    <details open={open} className="rounded-soft border-2 border-sand bg-white p-4">
      <summary className="flex min-h-11 cursor-pointer flex-wrap items-center gap-2 font-heading text-h3">
        {title} {badge}
      </summary>
      <div className="mt-3 flex flex-col gap-3">
        {children}
        <Raw value={raw} />
      </div>
    </details>
  );
}

export function StudentInspector() {
  const { id = "" } = useParams();
  const q = useDebug<Student>(`/api/admin/debug/students/${id}`);
  if (!q.data) return <Loading q={q} />;
  const d = q.data;
  const w = d.wallet;
  const failing = d.invariants.filter((c) => !c.ok);
  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="font-heading text-h2">{d.user.nickname}</h2>
        <Pill>{d.user.ui_language}</Pill>
        <Link
          className="text-small font-semibold text-primary underline"
          to={`/admin/users/${d.user.id}`}
        >
          Change this account (admin actions) →
        </Link>
        <SmallButton onClick={() => void q.refetch()}>Refresh</SmallButton>
      </header>

      <Fold
        title="Invariants"
        raw={d.invariants}
        badge={
          failing.length ? (
            <Pill tone="warn">{failing.length} failing</Pill>
          ) : (
            <Pill tone="on">all pass</Pill>
          )
        }
      >
        <ul className="flex flex-col gap-2 text-small">
          {d.invariants.map((c) => (
            <li key={c.check} className="flex flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <Pill tone={c.ok ? "on" : "warn"}>{c.ok ? "pass" : "FAIL"}</Pill>
                <code>{c.check}</code> {c.description}
              </span>
              {!c.ok && (
                <pre className="whitespace-pre-wrap break-words rounded-soft border-2 border-danger p-2">
                  {JSON.stringify(c.rows, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </Fold>

      <Fold title="Wallet" raw={w}>
        <KV
          items={[
            [
              "Coins",
              `${w.coins} = free ${w.free} + earned ${w.earned} + purchased ${w.purchased}`,
            ],
            ["Earned today", `${w.earned_today} / ${w.daily_earn_cap} (DAILY_EARN_CAP)`],
            [
              "Exam Pass",
              w.pass_active
                ? `active until ${when(w.pass_until)} · ${w.pass_used_today}/${w.pass_daily_limit} used today`
                : w.pass_until
                  ? `ended ${when(w.pass_until)}`
                  : "never",
            ],
            [
              "Today's refill row",
              w.has_daily_row_today ? "written" : "not yet (written on their next visit)",
            ],
            ["Spending order", w.spending_order.join(" → ")],
          ]}
        />
        {w.days.map((day) => (
          <details key={day.day} className="text-small">
            <summary className="min-h-11 cursor-pointer font-semibold">
              {day.day}: net {day.net >= 0 ? "+" : ""}
              {day.net}, earned {day.earned} · {day.rows.length} rows
            </summary>
            <DataTable
              rows={day.rows}
              rowKey={(r) => `${r.created_at}${r.kind}${r.bucket}${r.ref}`}
              columns={[
                { label: "Time", render: (r) => when(r.created_at).slice(11) },
                { label: "Bucket", render: (r) => r.bucket },
                { label: "Kind", render: (r) => r.kind },
                { label: "Delta", render: (r) => r.delta },
                {
                  label: "Ref",
                  render: (r) =>
                    r.ref && /^[0-9a-f-]{36}$/.test(r.ref) ? (
                      <Link className="text-primary underline" to={`/admin/debug/jobs/${r.ref}`}>
                        job {r.ref.slice(0, 8)}
                      </Link>
                    ) : (
                      (r.ref ?? "—")
                    ),
                },
              ]}
            />
          </details>
        ))}
      </Fold>

      <PricePanel
        userId={d.user.id}
        chapters={d.learning.mastery.map((m) => ({ id: m.chapter_id, title: m.chapter }))}
      />

      <Fold title="Points and streak" raw={d.points} open={false}>
        <KV
          items={[
            ["Points", d.points.total],
            ["Streak", `${d.points.streak} days`],
          ]}
        />
        <DataTable
          rows={d.points.ranks}
          rowKey={(r) => `${r.scope}${r.world_id}${r.period}`}
          columns={[
            {
              label: "Board",
              render: (r) => (r.scope === "world" ? `class ${r.world_id?.slice(0, 8)}` : "global"),
            },
            { label: "Period", render: (r) => r.period },
            { label: "Rank", render: (r) => r.rank ?? (r.opted_in ? "—" : "opted out") },
            { label: "Points", render: (r) => r.points },
          ]}
        />
        <DataTable
          rows={d.points.rows}
          rowKey={(r) => `${r.created_at}${r.reason}${r.ref}`}
          columns={[
            { label: "When", render: (r) => when(r.created_at) },
            { label: "Reason", render: (r) => r.reason },
            { label: "Delta", render: (r) => r.delta },
            { label: "Ref", render: (r) => r.ref },
          ]}
        />
      </Fold>

      <Fold title="Levels and mastery" raw={d.learning} open={false}>
        <DataTable
          rows={d.learning.levels}
          rowKey={(l) => l.course_id}
          empty="No placement yet."
          columns={[
            { label: "Course", render: (l) => l.course },
            { label: "Level (placement)", render: (l) => l.level },
            { label: "Placed", render: (l) => when(l.placed_at) },
            { label: "Goal", render: (l) => l.goal ?? "—" },
          ]}
        />
        <DataTable
          rows={d.learning.mastery}
          rowKey={(m) => m.chapter_id}
          empty="No chapter mastery yet."
          columns={[
            { label: "Chapter", render: (m) => m.chapter },
            { label: "Mastery", render: (m) => `${m.mastery}%` },
            { label: "Weak spot", render: (m) => (m.weak ? <Pill tone="warn">weak</Pill> : "—") },
          ]}
        />
      </Fold>

      <Fold title="Today's challenges" raw={d.daily} open={false}>
        {d.daily ? (
          <>
            <KV
              items={[
                ["Planned by", d.daily.planned_by],
                [
                  "Plan job",
                  d.daily.plan_job_id ? (
                    <Link
                      key="p"
                      className="text-primary underline"
                      to={`/admin/debug/jobs/${d.daily.plan_job_id}`}
                    >
                      {d.daily.plan_job_id.slice(0, 8)}
                    </Link>
                  ) : (
                    "—"
                  ),
                ],
                ["Seen", d.daily.seen_at ? when(d.daily.seen_at) : "not yet"],
              ]}
            />
            <DataTable
              rows={d.daily.challenges}
              rowKey={(c) => `${c.type}${c.chapter_id ?? ""}`}
              columns={[
                { label: "Type", render: (c) => c.type },
                { label: "Progress", render: (c) => `${c.progress}/${c.target}` },
                { label: "Done", render: (c) => (c.done ? "yes" : "—") },
                { label: "Why", render: (c) => c.why ?? "—" },
              ]}
            />
          </>
        ) : (
          <p className="text-small">
            No daily state today (they haven&apos;t opened the app today).
          </p>
        )}
      </Fold>

      <Fold title="Activity" raw={d.activity} open={false}>
        <h3 className="font-semibold">Jobs</h3>
        <DataTable
          rows={d.activity.jobs}
          rowKey={(j) => j.id}
          columns={[
            {
              label: "Job",
              render: (j) => (
                <Link
                  className="font-semibold text-primary underline"
                  to={`/admin/debug/jobs/${j.id}`}
                >
                  {j.kind}
                </Link>
              ),
            },
            { label: "Status", render: (j) => j.status },
            { label: "Cost", render: (j) => j.cost },
            { label: "Error", render: (j) => plainError(j.error) },
            { label: "Created", render: (j) => when(j.created_at) },
          ]}
        />
        <h3 className="font-semibold">Quiz attempts</h3>
        <DataTable
          rows={d.activity.quiz_attempts}
          rowKey={(a) => a.id}
          columns={[
            { label: "Level · lang", render: (a) => `${a.level} · ${a.language}` },
            { label: "Status", render: (a) => a.status },
            { label: "Score", render: (a) => a.score },
            { label: "Points", render: (a) => a.points },
            { label: "Second tries", render: (a) => a.second_tries },
            { label: "Answers", render: (a) => (a.answers ?? []).length },
          ]}
        />
        <h3 className="font-semibold">Tutor sessions</h3>
        <DataTable
          rows={d.activity.tutor_sessions}
          rowKey={(t) => t.id}
          columns={[
            { label: "Status", render: (t) => t.status },
            { label: "Turns", render: (t) => t.turns },
            { label: "Hints", render: (t) => t.hints_used },
            { label: "Stuck", render: (t) => t.stuck_count },
            { label: "Mid turns", render: (t) => t.escalations },
            { label: "Summary", render: (t) => (t.summary ? "yes" : "—") },
          ]}
        />
        <h3 className="font-semibold">Teach-Back</h3>
        <DataTable
          rows={d.activity.peer_answers}
          rowKey={(a) => a.id}
          empty="No answers."
          columns={[
            { label: "Status", render: (a) => a.status },
            { label: "Score", render: (a) => a.ai_score ?? "—" },
            { label: "Confidence", render: (a) => a.ai_confidence ?? "—" },
            { label: "Reviewed by mid", render: (a) => (a.reviewed_by_mid ? "yes" : "—") },
            { label: "Rewarded", render: (a) => (a.rewarded ? "yes" : "—") },
          ]}
        />
        <p className="text-small">
          {d.activity.peer_questions.length} questions asked · {d.activity.flashcard_reviews.length}{" "}
          flashcards in review
        </p>
      </Fold>
    </div>
  );
}

function PricePanel({
  userId,
  chapters,
}: {
  userId: string;
  chapters: { id: string; title: string }[];
}) {
  const [activity, setActivity] = useState<string>("quiz");
  const [chapter, setChapter] = useState(chapters[0]?.id ?? "");
  const [level, setLevel] = useState("intermediate");
  const [ask, setAsk] = useState<string | null>(null);
  const res = useQuery({
    queryKey: ["admin", "debug", "price", ask],
    queryFn: () => adminCall<PriceExplain>(ask as string),
    enabled: ask !== null,
  });
  const needs = NEEDS_CHAPTER.has(activity);
  return (
    <Section title="Explain price">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setAsk(
            `/api/admin/debug/students/${userId}/price${qs({
              activity,
              level,
              chapter_id: needs ? chapter : undefined,
            })}`,
          );
        }}
      >
        <Field label="Activity">
          <select
            className={inputClass}
            value={activity}
            onChange={(e) => setActivity(e.target.value)}
          >
            {ACTIVITIES.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </Field>
        {needs && (
          <Field label="Chapter (id)">
            {chapters.length ? (
              <select
                className={inputClass}
                value={chapter}
                onChange={(e) => setChapter(e.target.value)}
              >
                {chapters.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className={inputClass}
                value={chapter}
                onChange={(e) => setChapter(e.target.value)}
              />
            )}
          </Field>
        )}
        <Field label="Level">
          <select className={inputClass} value={level} onChange={(e) => setLevel(e.target.value)}>
            {["beginner", "intermediate", "advanced"].map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
        </Field>
        <SmallButton type="submit">Explain</SmallButton>
      </form>
      <ErrorNote error={res.error} />
      {res.data && (
        <div className="mt-3 flex flex-col gap-2 text-small">
          <p className="font-semibold">
            Pays {res.data.pays} {res.data.exam_pass && "(Exam Pass)"}
            {!res.data.affordable && <Pill tone="warn">can&apos;t afford it</Pill>}
          </p>
          <ol className="list-decimal ps-5">
            {res.data.steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </div>
      )}
    </Section>
  );
}
