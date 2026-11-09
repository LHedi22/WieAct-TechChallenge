// Read-only admin pages (phase B): users, worlds, content, arena, jobs, cache, admin log.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import {
  AnswerActions,
  CachePurge,
  ChapterActions,
  ContentEditor,
  CourseActions,
  DocumentActions,
  JobActions,
  MemberRemove,
  QuestionActions,
  UserActions,
  WorldActions,
} from "./actions";
import { adminCall } from "./adminApi";
import { plainError, when } from "./format";
import { ListView, DataTable, Json, type Column } from "./table";
import type {
  ActionRow,
  DocumentRow,
  AnswerRow,
  CacheRow,
  ContentKind,
  ContentRow,
  JobRow,
  QuestionRow,
  UserDetail,
  UserRow,
  WorldDetail,
  WorldRow,
} from "./types";
import { ErrorNote, Pill, Section } from "./ui";

const LANGS = ["en", "fr", "ar", "ar-TN"];
const LEVELS = ["beginner", "intermediate", "advanced"];
const short = (id: string | null | undefined) => (id ? id.slice(0, 8) : "—");
const kb = (n: number) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} kB`);

function useDetail<T>(path: string) {
  return useQuery({ queryKey: ["admin", path], queryFn: () => adminCall<T>(path) });
}

function Back({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to} className="text-small font-semibold text-primary underline">
      ← {label}
    </Link>
  );
}

function Loading({ q }: { q: { isPending: boolean; error: unknown } }) {
  if (q.error) return <ErrorNote error={q.error} />;
  return q.isPending ? <p className="text-small">Loading…</p> : null;
}

// --- users ---------------------------------------------------------------------------------------
export function UsersPage() {
  return (
    <Routes>
      <Route index element={<UserList />} />
      <Route path=":id" element={<UserDetailPage />} />
    </Routes>
  );
}

function UserList() {
  const nav = useNavigate();
  const cols: Column<UserRow>[] = [
    {
      label: "Nickname",
      render: (u) => (
        <span className="font-semibold">
          {u.nickname} {u.dev_user && <Pill>dev</Pill>}
        </span>
      ),
    },
    { label: "Created", render: (u) => when(u.created_at) },
    { label: "Lang", render: (u) => u.ui_language },
    { label: "Worlds", render: (u) => u.worlds },
    {
      label: "Coins (free/earned/bought)",
      render: (u) =>
        `${u.wallet.coins} (${u.wallet.free}/${u.wallet.earned}/${u.wallet.purchased})`,
    },
    { label: "Points", render: (u) => u.points },
    { label: "Streak", render: (u) => u.streak },
    {
      label: "Exam Pass",
      render: (u) => (u.wallet.pass_active ? `until ${when(u.wallet.pass_until)}` : "—"),
    },
    { label: "Last seen", render: (u) => when(u.last_seen) },
  ];
  return (
    <ListView<UserRow>
      title="Users"
      path="/api/admin/users"
      specs={[
        { key: "q", label: "Nickname", placeholder: "search" },
        { key: "language", label: "Language", options: LANGS },
      ]}
      columns={cols}
      rowKey={(u) => u.id}
      onOpen={(u) => nav(`/admin/users/${u.id}`)}
      intro={
        <p className="text-small text-ink/80">
          Wallets are summed from the coin ledger (today&apos;s free coins included), never a stored
          balance.
        </p>
      }
    />
  );
}

function UserDetailPage() {
  const { id = "" } = useParams();
  const q = useDetail<UserDetail>(`/api/admin/users/${id}`);
  return (
    <div className="flex flex-col gap-4">
      <Back to="/admin/users" label="Users" />
      <Loading q={q} />
      {q.data && <UserView u={q.data} extra={<UserActions u={q.data} />} />}
    </div>
  );
}

export function UserView({ u, extra }: { u: UserDetail; extra?: React.ReactNode }) {
  return (
    <>
      <h1 className="font-heading text-h2">{u.nickname}</h1>
      <div className="flex flex-wrap gap-2 text-small">
        <Pill>{u.ui_language}</Pill>
        <Pill>created {when(u.created_at)}</Pill>
        <Pill>
          {u.wallet.coins} coins · free {u.wallet.free} · earned {u.wallet.earned} · bought{" "}
          {u.wallet.purchased}
        </Pill>
        <Pill>{u.points} points</Pill>
        <Pill>streak {u.streak}</Pill>
        {u.wallet.pass_active && <Pill tone="on">Exam Pass until {when(u.wallet.pass_until)}</Pill>}
        {u.dev_user && <Pill>dev user (no password)</Pill>}
      </div>
      {extra}
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Worlds">
          <ul className="text-small">
            {u.worlds.map((w) => (
              <li key={w.id}>
                <Link className="text-primary underline" to={`/admin/worlds/${w.id}`}>
                  {w.name}
                </Link>{" "}
                · {w.join_code} · joined {when(w.joined_at)}
              </li>
            ))}
            {u.worlds.length === 0 && <li className="text-ink/70">None</li>}
          </ul>
        </Section>
        <Section title="Levels and activity">
          <ul className="text-small">
            {u.levels.map((l) => (
              <li key={l.course_id}>
                {l.course}: <strong>{l.level}</strong> (placed {when(l.placed_at)})
              </li>
            ))}
            {Object.entries(u.counts).map(([k, v]) => (
              <li key={k}>
                {k.replace(/_/g, " ")}: {v}
              </li>
            ))}
          </ul>
        </Section>
      </div>
      <Section title="Coin ledger (latest 50)">
        <DataTable
          rows={u.coin_ledger}
          rowKey={(r) => `${r.created_at}${r.kind}${r.ref}${r.bucket}${r.delta}`}
          columns={[
            { label: "When", render: (r) => when(r.created_at) },
            { label: "Day", render: (r) => r.day },
            { label: "Bucket", render: (r) => r.bucket },
            { label: "Kind", render: (r) => r.kind },
            { label: "Delta", render: (r) => (r.delta > 0 ? `+${r.delta}` : r.delta) },
            { label: "Ref", render: (r) => <code>{r.ref ?? "—"}</code> },
          ]}
        />
      </Section>
      <Section title="Points ledger (latest 50)">
        <DataTable
          rows={u.points_ledger}
          rowKey={(r) => `${r.created_at}${r.reason}${r.ref}`}
          columns={[
            { label: "When", render: (r) => when(r.created_at) },
            { label: "Reason", render: (r) => r.reason },
            { label: "Delta", render: (r) => r.delta },
            { label: "Ref", render: (r) => <code>{r.ref ?? "—"}</code> },
          ]}
        />
      </Section>
      <Section title="Recent jobs">
        <DataTable rows={u.jobs} rowKey={(j) => j.id} columns={jobColumns} />
      </Section>
    </>
  );
}

// --- worlds --------------------------------------------------------------------------------------
export function WorldsPage() {
  return (
    <Routes>
      <Route index element={<WorldList />} />
      <Route path=":id" element={<WorldDetailPage />} />
    </Routes>
  );
}

function WorldList() {
  const nav = useNavigate();
  return (
    <ListView<WorldRow>
      title="Worlds"
      path="/api/admin/worlds"
      specs={[{ key: "q", label: "Name or join code", placeholder: "search" }]}
      rowKey={(w) => w.id}
      onOpen={(w) => nav(`/admin/worlds/${w.id}`)}
      columns={[
        { label: "Name", render: (w) => <span className="font-semibold">{w.name}</span> },
        { label: "Join code", render: (w) => <code>{w.join_code}</code> },
        { label: "Creator", render: (w) => w.creator ?? "—" },
        { label: "Members", render: (w) => w.members },
        { label: "Courses", render: (w) => w.courses },
        {
          label: "Documents",
          render: (w) => (
            <>
              {w.documents}
              {w.failed_documents > 0 && <Pill tone="warn">{w.failed_documents} failed</Pill>}
            </>
          ),
        },
        { label: "Class pool", render: (w) => w.pool },
      ]}
    />
  );
}

function WorldDetailPage() {
  const { id = "" } = useParams();
  const q = useDetail<WorldDetail>(`/api/admin/worlds/${id}`);
  return (
    <div className="flex flex-col gap-4">
      <Back to="/admin/worlds" label="Worlds" />
      <Loading q={q} />
      {q.data && <WorldView w={q.data} extra={<WorldActions w={q.data} />} />}
    </div>
  );
}

export function WorldView({ w, extra }: { w: WorldDetail; extra?: React.ReactNode }) {
  return (
    <>
      <h1 className="font-heading text-h2">{w.name}</h1>
      <div className="flex flex-wrap gap-2 text-small">
        <Pill>join code {w.join_code}</Pill>
        <Pill>creator {w.creator ?? "—"}</Pill>
        <Pill>{w.members.length} members</Pill>
        <Pill>class pool {w.pool.balance}</Pill>
      </div>
      {extra}
      {w.courses.map((c) => (
        <Section
          key={c.id}
          title={c.name}
          actions={c.exam_date ? <Pill>exam {c.exam_date}</Pill> : undefined}
        >
          {extra && <CourseActions c={c} />}
          {c.chapters.map((ch) => (
            <div key={ch.id} className="mb-3">
              <h3 className="font-semibold">
                {ch.idx + 1}. {ch.title}
              </h3>
              {extra && <ChapterActions ch={ch} />}
              <DataTable
                rows={ch.documents}
                rowKey={(d) => d.id}
                empty="No documents."
                columns={[
                  { label: "File", render: (d) => d.filename },
                  { label: "Kind", render: (d) => d.kind },
                  { label: "Size", render: (d) => kb(d.size) },
                  {
                    label: "Status",
                    render: (d) => (
                      <Pill
                        tone={
                          d.status === "failed" ? "warn" : d.status === "ready" ? "on" : "neutral"
                        }
                      >
                        {d.status}
                        {d.status !== "ready" && d.status !== "failed" && ` ${d.progress}%`}
                      </Pill>
                    ),
                  },
                  { label: "Error", render: (d) => plainError(d.error) },
                  { label: "Pages", render: (d) => d.page_count ?? "—" },
                  { label: "Tagged by", render: (d) => d.tagged_by ?? "—" },
                  ...(extra
                    ? [
                        {
                          label: "Actions",
                          render: (d: DocumentRow) => (
                            <DocumentActions id={d.id} filename={d.filename} />
                          ),
                        },
                      ]
                    : []),
                ]}
              />
            </div>
          ))}
        </Section>
      ))}
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Members">
          <ul className="text-small">
            {w.members.map((m) => (
              <li key={m.id}>
                <Link className="text-primary underline" to={`/admin/users/${m.id}`}>
                  {m.nickname}
                </Link>{" "}
                · joined {when(m.joined_at)}{" "}
                {extra && <MemberRemove worldId={w.id} userId={m.id} nickname={m.nickname} />}
              </li>
            ))}
          </ul>
        </Section>
        <Section title="Class pool history">
          <DataTable
            rows={w.pool.history}
            rowKey={(r) => `${r.created_at}${r.kind}${r.delta}${r.ref}`}
            empty="No pool activity."
            columns={[
              { label: "When", render: (r) => when(r.created_at) },
              { label: "Kind", render: (r) => r.kind },
              { label: "Delta", render: (r) => r.delta },
              { label: "By", render: (r) => r.by ?? "—" },
            ]}
          />
        </Section>
      </div>
    </>
  );
}

// --- content -------------------------------------------------------------------------------------
const CONTENT_KINDS: { kind: ContentKind; label: string }[] = [
  { kind: "quiz_sets", label: "Quiz sets" },
  { kind: "study_assets", label: "Study assets" },
  { kind: "wisdom_tips", label: "Wisdom tips" },
  { kind: "placement_sets", label: "Placement sets" },
  { kind: "flashcards", label: "Flashcards" },
];

export function ContentPage() {
  return (
    <Routes>
      <Route index element={<ContentList />} />
      <Route path=":kind/:id" element={<ContentItemPage />} />
    </Routes>
  );
}

function ContentList() {
  const nav = useNavigate();
  const [kind, setKind] = useState<ContentKind>("quiz_sets");
  return (
    <div className="flex flex-col gap-4">
      <div role="tablist" aria-label="Content kind" className="flex flex-wrap gap-2">
        {CONTENT_KINDS.map((k) => (
          <button
            key={k.kind}
            type="button"
            role="tab"
            aria-selected={kind === k.kind}
            onClick={() => setKind(k.kind)}
            className={
              kind === k.kind
                ? "min-h-11 rounded-soft border-2 border-primary-dark bg-primary px-3 text-small font-semibold text-white"
                : "min-h-11 rounded-soft border-2 border-ink bg-white px-3 text-small font-semibold"
            }
          >
            {k.label}
          </button>
        ))}
      </div>
      <ListView<ContentRow>
        key={kind}
        title="Content"
        path={`/api/admin/content`}
        initial={{ kind }}
        specs={[
          { key: "chapter_id", label: "Chapter id", placeholder: "uuid" },
          { key: "level", label: "Level", options: LEVELS },
          { key: "language", label: "Language", options: LANGS },
          ...(kind === "study_assets"
            ? [{ key: "asset_kind", label: "Asset", options: ["notes", "map", "audio_script"] }]
            : []),
        ]}
        rowKey={(r) => r.id}
        onOpen={(r) => nav(`/admin/content/${kind}/${r.id}`)}
        columns={[
          { label: "Summary", render: (r) => r.summary },
          { label: "Chapter", render: (r) => <code>{short(r.chapter_id ?? r.course_id)}</code> },
          { label: "Level", render: (r) => r.level ?? "—" },
          { label: "Lang", render: (r) => r.language ?? "—" },
          { label: "Made by", render: (r) => r.provider ?? "—" },
          {
            label: "Edited",
            render: (r) => (r.edited_by_admin ? <Pill tone="warn">edited by admin</Pill> : "—"),
          },
          { label: "Created", render: (r) => when(r.created_at) },
        ]}
      />
    </div>
  );
}

function ContentItemPage() {
  const { kind = "", id = "" } = useParams();
  const q = useDetail<ContentRow>(`/api/admin/content/${kind}/${id}`);
  return (
    <div className="flex flex-col gap-4">
      <Back to="/admin/content" label="Content" />
      <Loading q={q} />
      {q.data && (
        <ContentView
          kind={kind as ContentKind}
          c={q.data}
          extra={<ContentEditor kind={kind as ContentKind} c={q.data} />}
        />
      )}
    </div>
  );
}

export function ContentView({
  c,
  extra,
}: {
  kind: ContentKind;
  c: ContentRow;
  extra?: React.ReactNode;
}) {
  return (
    <>
      <h1 className="font-heading text-h2">{c.summary}</h1>
      <div className="flex flex-wrap gap-2 text-small">
        <Pill>{c.level ?? "—"}</Pill>
        <Pill>{c.language ?? "—"}</Pill>
        <Pill>made by {c.provider ?? "unknown"}</Pill>
        {c.edited_by_admin && <Pill tone="warn">edited by admin: not pure AI output</Pill>}
      </div>
      {extra ?? <Json value={c.body} />}
    </>
  );
}

// --- arena ---------------------------------------------------------------------------------------
export function ArenaPage() {
  const [tab, setTab] = useState<"answers" | "questions">("answers");
  return (
    <div className="flex flex-col gap-4">
      <div role="tablist" aria-label="Arena" className="flex gap-2">
        {(["answers", "questions"] as const).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={
              tab === t
                ? "min-h-11 rounded-soft border-2 border-primary-dark bg-primary px-3 text-small font-semibold text-white"
                : "min-h-11 rounded-soft border-2 border-ink bg-white px-3 text-small font-semibold"
            }
          >
            {t === "answers" ? "Answers" : "Questions"}
          </button>
        ))}
      </div>
      {tab === "answers" ? <AnswerList /> : <QuestionList />}
    </div>
  );
}

const answerColumns: Column<AnswerRow>[] = [
  { label: "Question", render: (a) => <span className="line-clamp-2">{a.question}</span> },
  { label: "Answer", render: (a) => <span className="line-clamp-3">{a.text}</span> },
  { label: "By", render: (a) => a.author },
  {
    label: "Status",
    render: (a) => (
      <Pill tone={a.status === "pending_review" ? "warn" : "neutral"}>
        {a.status}
        {a.pinned && " · pinned"}
      </Pill>
    ),
  },
  { label: "Score", render: (a) => a.ai_score ?? "—" },
  { label: "Confidence", render: (a) => a.ai_confidence ?? "—" },
  { label: "Mid review", render: (a) => (a.reviewed_by_mid ? "yes" : "no") },
  { label: "Rewarded", render: (a) => (a.rewarded ? "yes" : "no") },
];

function AnswerList({ columns = answerColumns }: { columns?: Column<AnswerRow>[] }) {
  return (
    <ListView<AnswerRow>
      title="Arena answers"
      path="/api/admin/arena/answers"
      specs={[
        {
          key: "status",
          label: "Status",
          options: ["grading", "graded", "pending_review", "rejected", "failed"],
        },
        { key: "question_id", label: "Question id", placeholder: "uuid" },
      ]}
      rowKey={(a) => a.id}
      columns={[...columns, { label: "Actions", render: (a) => <AnswerActions a={a} /> }]}
    />
  );
}

const questionColumns: Column<QuestionRow>[] = [
  { label: "Question", render: (q) => <span className="line-clamp-3">{q.text}</span> },
  { label: "By", render: (q) => q.author },
  { label: "Lang", render: (q) => q.language },
  {
    label: "Status",
    render: (q) => (
      <Pill tone={q.status === "rejected" ? "warn" : "neutral"}>
        {q.status}
        {q.reject_reason && ` (${q.reject_reason})`}
      </Pill>
    ),
  },
  { label: "Answers", render: (q) => q.answers },
  { label: "Pinned", render: (q) => (q.pinned_answer_id ? "yes" : "—") },
  { label: "Asked", render: (q) => when(q.created_at) },
];

function QuestionList({ columns = questionColumns }: { columns?: Column<QuestionRow>[] }) {
  return (
    <ListView<QuestionRow>
      title="Arena questions"
      path="/api/admin/arena/questions"
      specs={[
        { key: "q", label: "Text", placeholder: "search" },
        { key: "status", label: "Status", options: ["pending", "open", "rejected"] },
      ]}
      rowKey={(q) => q.id}
      columns={[...columns, { label: "Actions", render: (q) => <QuestionActions q={q} /> }]}
    />
  );
}

// --- jobs ----------------------------------------------------------------------------------------
const jobColumns: Column<JobRow>[] = [
  { label: "Kind", render: (j) => <span className="font-semibold">{j.kind}</span> },
  { label: "Lane", render: (j) => j.lane },
  {
    label: "Status",
    render: (j) => (
      <Pill tone={j.status === "failed" ? "warn" : j.status === "done" ? "on" : "neutral"}>
        {j.status}
      </Pill>
    ),
  },
  { label: "Attempts", render: (j) => j.attempts },
  { label: "Not before", render: (j) => (j.not_before ? when(j.not_before) : "—") },
  { label: "Cost", render: (j) => j.cost },
  { label: "Quick", render: (j) => (j.quick_mode ? "yes" : "—") },
  {
    label: "Error",
    render: (j) =>
      j.error?.startsWith("deferred:") ? `waiting (${j.error.slice(9)})` : plainError(j.error),
  },
  { label: "Created", render: (j) => when(j.created_at) },
];

export function JobsList({ columns = jobColumns }: { columns?: Column<JobRow>[] }) {
  const summary =
    useDetail<{ lane: string; status: string; count: number }[]>("/api/admin/jobs/summary");
  return (
    <ListView<JobRow>
      title="Jobs"
      path="/api/admin/jobs"
      specs={[
        { key: "lane", label: "Lane", options: ["interactive", "background"] },
        {
          key: "status",
          label: "Status",
          options: ["queued", "running", "done", "failed", "cancelled"],
        },
        { key: "kind", label: "Kind", placeholder: "e.g. QUIZ_GENERATE" },
      ]}
      rowKey={(j) => j.id}
      columns={[
        ...columns,
        { label: "User", render: (j) => j.user ?? "—" },
        { label: "Actions", render: (j) => <JobActions j={j} /> },
      ]}
      intro={
        summary.data && (
          <div className="flex flex-wrap gap-2 text-small">
            {summary.data.map((r) => (
              <Pill
                key={`${r.lane}${r.status}`}
                tone={r.status === "queued" || r.status === "running" ? "on" : "neutral"}
              >
                {r.lane} · {r.status}: {r.count}
              </Pill>
            ))}
          </div>
        )
      }
    />
  );
}

// --- cache ---------------------------------------------------------------------------------------
const cacheColumns: Column<CacheRow>[] = [
  { label: "Task", render: (c) => c.task_kind },
  { label: "Provider", render: (c) => c.provider },
  { label: "Tier", render: (c) => c.model_tier },
  { label: "Hits", render: (c) => c.hits },
  { label: "Age", render: (c) => `${Math.round(c.age_s / 3600)} h` },
  { label: "Size", render: (c) => kb(c.size_bytes) },
  { label: "Key", render: (c) => <code className="break-all">{c.key.slice(0, 24)}…</code> },
];

export function CacheList({ columns = cacheColumns }: { columns?: Column<CacheRow>[] }) {
  const summary = useDetail<
    { task_kind: string; provider: string; entries: number; hits: number; size_bytes: number }[]
  >("/api/admin/cache/summary");
  return (
    <ListView<CacheRow>
      title="AI cache"
      path="/api/admin/cache"
      specs={[
        { key: "task_kind", label: "Task kind", placeholder: "e.g. NOTES_WRITE" },
        { key: "provider", label: "Provider", options: ["cloud", "local", "mock"] },
        { key: "q", label: "Key contains", placeholder: "key" },
      ]}
      rowKey={(c) => c.key}
      columns={columns}
      intro={
        summary.data && (
          <>
            <CachePurge />
            <DataTable
              rows={summary.data}
              rowKey={(r) => `${r.task_kind}${r.provider}`}
              empty="The cache is empty."
              columns={[
                { label: "Task", render: (r) => r.task_kind },
                { label: "Provider", render: (r) => r.provider },
                { label: "Entries", render: (r) => r.entries },
                { label: "Hits", render: (r) => r.hits },
                { label: "Size", render: (r) => kb(r.size_bytes) },
              ]}
            />
          </>
        )
      }
    />
  );
}

// --- admin log -----------------------------------------------------------------------------------
export function LogPage() {
  return (
    <ListView<ActionRow>
      title="Admin log"
      path="/api/admin/actions"
      specs={[
        { key: "action", label: "Action", placeholder: "e.g. switch.set" },
        {
          key: "target_kind",
          label: "Target",
          options: [
            "switch",
            "user",
            "world",
            "course",
            "chapter",
            "document",
            "job",
            "cache",
            "content",
            "answer",
            "question",
            "economy",
            "pool",
          ],
        },
        { key: "actor", label: "Who", placeholder: "name" },
      ]}
      rowKey={(a) => String(a.id)}
      columns={[
        { label: "When", render: (a) => when(a.ts) },
        { label: "Who", render: (a) => a.actor },
        { label: "Action", render: (a) => <code>{a.action}</code> },
        {
          label: "Target",
          render: (a) => (a.target_kind ? `${a.target_kind} ${short(a.target_id)}` : "—"),
        },
        { label: "Reason", render: (a) => a.reason ?? "—" },
        {
          label: "Change",
          render: (a) => (
            <details>
              <summary className="cursor-pointer">before / after</summary>
              <Json value={{ before: a.before, after: a.after }} />
            </details>
          ),
        },
      ]}
    />
  );
}
