// /admin/debug: the AI pipeline inspector (backend app/admin/debug.py) and the student inspector
// (app/admin/inspect.py). Read-only: changes go through the admin actions it links to. Polling
// pages refresh every 2.5 s while the tab is visible (TanStack Query stops when it is hidden).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { cx } from "@/components/cx";
import { adminCall } from "./adminApi";
import type {
  CallDetail,
  CallRow,
  JobEvent,
  Live,
  ReplayResult,
  Routing,
  Timeline,
  Trace,
} from "./debugTypes";
import { inputClass, plainError, when } from "./format";
import { DataTable, Json } from "./table";
import { OUTCOME, callColumns, useDebug } from "./debugKit";
import { KV, Loading } from "./debugUi";
import { ErrorNote, Field, Pill, Section, SmallButton } from "./ui";

const TRACE_MINUTES = [10, 30, 60, 120];

const TABS = [
  { to: "live", label: "Live" },
  { to: "routing", label: "Routing check" },
  { to: "jobs", label: "Job timeline" },
];

export function DebugPage() {
  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-h2">Debug</h1>
        <nav aria-label="Debug sections" className="flex flex-wrap gap-1">
          {TABS.map((t) => (
            <NavLink
              key={t.to}
              to={`/admin/debug/${t.to}`}
              className={({ isActive }) =>
                cx(
                  "flex min-h-11 items-center rounded-soft border-2 px-3 text-small font-semibold",
                  isActive
                    ? "border-primary-dark bg-primary text-white"
                    : "border-sand bg-white text-ink",
                )
              }
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <Routes>
        <Route index element={<LivePage />} />
        <Route path="live" element={<LivePage />} />
        <Route path="routing" element={<RoutingPage />} />
        <Route path="jobs" element={<JobLookup />} />
        <Route path="jobs/:id" element={<JobTimelinePage />} />
        <Route path="calls/:id" element={<CallPage />} />
      </Routes>
    </div>
  );
}

// --- outcome colours (each square also carries a letter: never colour alone) -------------------

function OutcomeSquare({ c }: { c: CallRow }) {
  const o = OUTCOME[c.outcome] ?? OUTCOME.error;
  const title = `#${c.id} ${c.task_kind} · ${c.tier} · ${o.label}${c.debug ? " · replay" : ""}`;
  return (
    <Link
      to={`/admin/debug/calls/${c.id}`}
      title={title}
      aria-label={title}
      className={cx(
        "flex h-8 w-8 items-center justify-center rounded-soft text-small font-semibold",
        o.cls,
        c.debug && "opacity-60",
      )}
    >
      {o.letter}
    </Link>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-2 text-small" aria-label="Legend">
      {Object.entries(OUTCOME).map(([k, o]) => (
        <li key={k} className="flex items-center gap-1">
          <span className={cx("flex h-6 w-6 items-center justify-center rounded-soft", o.cls)}>
            {o.letter}
          </span>
          {o.label}
        </li>
      ))}
    </ul>
  );
}

// --- Live ----------------------------------------------------------------------------------------
function LivePage() {
  const q = useDebug<Live>("/api/admin/debug/live", true);
  if (!q.data) return <Loading q={q} />;
  const d = q.data;
  const perMinute = groupMinutes(d.calls_per_minute);
  return (
    <div className="flex flex-col gap-4">
      <TraceSwitch on={d.trace_on} until={d.flags.trace_prompts_until} env={d.app_env} />
      <Section title="Worker">
        {d.workers.length === 0 && (
          <p className="text-small">
            No worker heartbeat yet. Is <code>python -m app.worker</code> running?
          </p>
        )}
        <div className="flex flex-col gap-4">
          {d.workers.map((w) => (
            <div key={w.worker_id} className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <code className="text-small">{w.worker_id}</code>
                <Pill tone={w.fresh ? "on" : "warn"}>
                  {w.fresh ? `beat ${w.age_s}s ago` : `stale: ${w.age_s}s`}
                </Pill>
                {w.provider && <Pill>provider {w.provider}</Pill>}
                <Pill tone={w.slot_live ? "on" : "neutral"}>
                  slot {w.slot_live ? "live" : "off"}
                </Pill>
                {w.offline && <Pill tone="warn">offline ({w.offline_reason ?? "?"})</Pill>}
              </div>
              <KV
                items={[
                  [
                    "In flight",
                    `interactive ${w.in_flight?.interactive ?? 0}/${w.lane_limits?.interactive ?? "?"} · background ${w.in_flight?.background ?? 0}/${w.lane_limits?.background ?? "?"}`,
                  ],
                  [
                    "Model calls in flight",
                    w.limiter
                      ? `${w.limiter.active}/${w.limiter.concurrency} (max seen ${w.limiter.max_active}) · waiting interactive ${w.limiter.waiting.interactive ?? 0}, background ${w.limiter.waiting.background ?? 0}`
                      : "—",
                  ],
                  [
                    "Chat bucket",
                    w.limiter
                      ? `${w.limiter.buckets.chat?.tokens} / ${w.limiter.buckets.chat?.capacity} tokens · ${w.limiter.buckets.chat?.rpm} rpm · ${w.limiter.rpm_last_60s.chat} calls in the last 60 s`
                      : "—",
                  ],
                  [
                    "Embeddings bucket",
                    w.limiter
                      ? `${w.limiter.buckets.embed?.tokens} / ${w.limiter.buckets.embed?.capacity} · ${w.limiter.rpm_last_60s.embed} in 60 s`
                      : "—",
                  ],
                  [
                    "Quota",
                    w.quota
                      ? `remaining ${w.quota.remaining ?? "unknown"}${w.quota.low ? " (low: background paused " + w.quota.background_pause_s + " s)" : ""}`
                      : "—",
                  ],
                  [
                    "Current jobs",
                    w.job_ids?.length ? (
                      <span className="flex flex-wrap gap-2">
                        {w.job_ids.map((j) => (
                          <Link
                            key={j}
                            className="text-primary underline"
                            to={`/admin/debug/jobs/${j}`}
                          >
                            {j.slice(0, 8)}
                          </Link>
                        ))}
                      </span>
                    ) : (
                      "none"
                    ),
                  ],
                  [
                    "Last error",
                    w.last_error ? (
                      <Link
                        className="text-primary underline"
                        to={`/admin/debug/jobs/${w.last_error.job_id}`}
                      >
                        {when(w.last_error.t)} · {w.last_error.kind} ·{" "}
                        {plainError(w.last_error.error)}
                      </Link>
                    ) : (
                      "none"
                    ),
                  ],
                ]}
              />
              {w.status_error && <ErrorNote error={`heartbeat: ${w.status_error}`} />}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Queue">
        <DataTable
          rows={d.queue}
          rowKey={(r) => r.lane}
          columns={[
            { label: "Lane", render: (r) => r.lane },
            { label: "Ready", render: (r) => r.ready },
            { label: "Waiting (not_before)", render: (r) => r.waiting },
            { label: "Running", render: (r) => r.running },
            {
              label: "Next not_before",
              render: (r) => (r.next_not_before ? when(r.next_not_before) : "—"),
            },
          ]}
        />
      </Section>
      <Section title="Calls per minute (last 15 min, cache hits excluded)">
        {perMinute.length === 0 ? (
          <p className="text-small">No calls.</p>
        ) : (
          <DataTable
            rows={perMinute}
            rowKey={(r) => r.minute}
            columns={[
              { label: "Minute", render: (r) => when(r.minute).slice(11) },
              { label: "Compact", render: (r) => r.compact },
              { label: "Mid", render: (r) => r.mid },
              { label: "Embed", render: (r) => r.embed },
            ]}
          />
        )}
      </Section>
      <Section title="Active switches">
        <div className="flex flex-wrap gap-2 text-small">
          {Object.entries(d.flags).map(([k, v]) => (
            <Pill key={k} tone={v === null || v === false || v === "auto" ? "neutral" : "on"}>
              {k}: {v === null ? "default" : String(v)}
            </Pill>
          ))}
        </div>
      </Section>
      <Section title="Last 50 calls (newest first)">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-1">
            {d.last_calls.map((c) => (
              <OutcomeSquare key={c.id} c={c} />
            ))}
          </div>
          <Legend />
        </div>
      </Section>
    </div>
  );
}

function groupMinutes(rows: Live["calls_per_minute"]) {
  const by = new Map<string, { minute: string; compact: number; mid: number; embed: number }>();
  for (const r of rows) {
    const row = by.get(r.minute) ?? { minute: r.minute, compact: 0, mid: 0, embed: 0 };
    if (r.tier === "compact" || r.tier === "mid" || r.tier === "embed") row[r.tier] += r.calls;
    by.set(r.minute, row);
  }
  return [...by.values()].reverse();
}

function TraceSwitch({ on, until, env }: { on: boolean; until: unknown; env: string }) {
  const qc = useQueryClient();
  const [minutes, setMinutes] = useState(30);
  const set = useMutation({
    mutationFn: (value: number) =>
      adminCall("/api/admin/switches/trace_prompts", {
        method: "PUT",
        body: { value, reason: value ? "debugging with prompt traces" : null },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin"] }),
  });
  return (
    <Section
      title="Prompt traces"
      className={on ? "border-terracotta-ink" : undefined}
      actions={<Pill tone={on ? "warn" : "neutral"}>{on ? "ON" : "off"}</Pill>}
    >
      <div className="flex flex-col gap-3 text-small">
        <p>
          While on, the gateway stores each call&apos;s prompt and reply (capped at 16 kB per field,
          keys and the student&apos;s nickname redacted) for 24 hours. Prompts carry course text and
          student answers.
        </p>
        {on && (
          <p
            role="status"
            className="rounded-soft border-2 border-terracotta-ink bg-terracotta-light/25 px-3 py-2 font-semibold"
          >
            Tracing is on until {typeof until === "string" ? when(until) : "?"}.
            {env === "production" && " This is production: turn it off before a user test."}
          </p>
        )}
        <div className="flex flex-wrap items-end gap-2">
          {!on && (
            <Field label="Turn on for">
              <select
                className={inputClass}
                value={minutes}
                onChange={(e) => setMinutes(Number(e.target.value))}
              >
                {TRACE_MINUTES.map((m) => (
                  <option key={m} value={m}>
                    {m} minutes
                  </option>
                ))}
              </select>
            </Field>
          )}
          <SmallButton
            tone={on ? "danger" : "primary"}
            disabled={set.isPending}
            onClick={() => set.mutate(on ? 0 : minutes)}
          >
            {on ? "Turn off now" : "Turn on"}
          </SmallButton>
        </div>
        <ErrorNote error={set.error} />
      </div>
    </Section>
  );
}

// --- job timeline --------------------------------------------------------------------------------
function JobLookup() {
  const nav = useNavigate();
  const [id, setId] = useState("");
  return (
    <Section title="Open a job">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (id.trim()) nav(`/admin/debug/jobs/${id.trim()}`);
        }}
      >
        <Field label="Job id">
          <input className={inputClass} value={id} onChange={(e) => setId(e.target.value)} />
        </Field>
        <SmallButton type="submit">Open</SmallButton>
      </form>
      <p className="mt-2 text-small">
        Or pick one from the{" "}
        <Link className="text-primary underline" to="/admin/jobs">
          Jobs
        </Link>{" "}
        page, the Live page or a student.
      </p>
    </Section>
  );
}

/** Local time with seconds and milliseconds: 01:42:07.315 */
function clock(iso: string): string {
  const d = new Date(iso);
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

function eventText(e: JobEvent): string {
  switch (e.type) {
    case "created":
      return `created (${e.lane}, cost ${e.cost})`;
    case "claimed":
      return `claimed by ${e.worker ?? "worker"}`;
    case "stage":
      return `stage: ${e.stage}`;
    case "deferred":
      return `deferred ${e.delay_s ?? "?"} s: ${e.reason?.replace("deferred:", "") ?? "?"}`;
    case "requeued":
      return "requeued";
    case "done":
      return e.quick_mode ? "done (Quick mode)" : "done";
    case "failed":
      return `failed: ${plainError(e.error)}`;
    case "swept":
      return "lease expired: failed and refunded";
    default:
      return e.type;
  }
}

function JobTimelinePage() {
  const { id = "" } = useParams();
  const q = useDebug<Timeline>(`/api/admin/debug/jobs/${id}`, true);
  if (!q.data) return <Loading q={q} />;
  const { job, events, calls, coins, pool, result } = q.data;
  return (
    <div className="flex flex-col gap-4">
      <Section
        title={`Job ${job.kind}`}
        actions={
          <Pill tone={job.status === "failed" ? "warn" : job.status === "done" ? "on" : "neutral"}>
            {job.status}
          </Pill>
        }
      >
        <KV
          items={[
            ["Id", <code key="id">{job.id}</code>],
            ["Lane", job.lane],
            [
              "Student",
              job.user_id ? (
                <Link
                  key="u"
                  className="text-primary underline"
                  to={`/admin/debug/students/${job.user_id}`}
                >
                  {job.user ?? job.user_id.slice(0, 8)}
                </Link>
              ) : (
                "— (class job)"
              ),
            ],
            ["Attempts", job.attempts],
            ["Provider", job.provider ?? "—"],
            ["Cost", job.cost],
            ["Quick mode", job.quick_mode ? "yes" : "no"],
            ["Error", plainError(job.error)],
            [
              "Created / finished",
              `${when(job.created_at)} → ${job.finished_at ? when(job.finished_at) : "…"}`,
            ],
          ]}
        />
        <p className="mt-3 text-small">
          Retry, cancel or fail it from the{" "}
          <Link className="text-primary underline" to="/admin/jobs">
            Jobs
          </Link>{" "}
          page (admin actions).
        </p>
      </Section>
      <Section title="Timeline">
        <ol className="flex flex-col gap-1 border-s-2 border-sand ps-3 text-small">
          {events.map((e, i) => (
            <li key={i}>
              <span className="font-mono text-ink/80">{clock(e.t)}</span> {eventText(e)}
            </li>
          ))}
        </ol>
      </Section>
      <Section title={`Model calls (${calls.length})`}>
        <DataTable
          rows={calls}
          rowKey={(c) => String(c.id)}
          columns={callColumns}
          empty="No model call (yet)."
        />
      </Section>
      <Section title="Coins">
        <DataTable
          rows={[
            ...coins.map((c) => ({ ...c, src: "wallet" })),
            ...pool.map((p) => ({
              ...p,
              src: "class pool",
              bucket: "pool",
              day: "",
              created_at: "",
            })),
          ]}
          rowKey={(r) => `${r.src}${r.kind}${r.bucket}${r.delta}`}
          empty="No coin rows (free or cached)."
          columns={[
            { label: "Where", render: (r) => r.src },
            { label: "Kind", render: (r) => r.kind },
            { label: "Bucket", render: (r) => r.bucket },
            { label: "Delta", render: (r) => r.delta },
            { label: "Day", render: (r) => r.day || "—" },
          ]}
        />
      </Section>
      <Section title="Result">
        <Json value={result ?? job.error} />
      </Section>
    </div>
  );
}

// --- call detail + replay ------------------------------------------------------------------------
function TraceView({ t }: { t: Trace }) {
  return (
    <div className="flex flex-col gap-3">
      <h3 className="font-semibold">Messages sent</h3>
      {(t.messages ?? []).map((m, i) => (
        <div key={i} className="rounded-soft border-2 border-sand p-2">
          <Pill>{m.role}</Pill>
          <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words text-small">
            {m.content}
          </pre>
        </div>
      ))}
      <h3 className="font-semibold">Raw reply</h3>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-soft border-2 border-sand bg-whitewash p-2 text-small">
        {t.reply ?? "— (no reply: the call failed)"}
      </pre>
      {t.reply_without_think !== null && (
        <>
          <h3 className="font-semibold">After stripping &lt;think&gt;</h3>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-soft border-2 border-sand bg-whitewash p-2 text-small">
            {t.reply_without_think}
          </pre>
        </>
      )}
      <h3 className="font-semibold">Tolerant JSON parse</h3>
      <Json value={t.parsed ?? "— (text reply, or no JSON found)"} />
      {t.error && (
        <>
          <h3 className="font-semibold">Errors (call, validation, job)</h3>
          <pre className="whitespace-pre-wrap break-words rounded-soft border-2 border-danger p-2 text-small text-danger">
            {t.error}
          </pre>
        </>
      )}
    </div>
  );
}

function CallPage() {
  const { id = "" } = useParams();
  const q = useDebug<CallDetail>(`/api/admin/debug/calls/${id}`);
  if (!q.data) return <Loading q={q} />;
  const { call, trace, repair, replay, tracing_note } = q.data;
  return (
    <div className="flex flex-col gap-4">
      <Section
        title={`Call #${call.id} · ${call.task_kind}`}
        actions={call.debug ? <Pill>replay</Pill> : undefined}
      >
        <KV
          items={[
            ["When", when(call.ts)],
            ["Tier / model", `${call.tier} · ${call.model} (${call.provider})`],
            ["Pattern", call.pattern],
            [
              "Outcome",
              `${OUTCOME[call.outcome]?.label ?? call.outcome}${call.status_code ? ` · ${call.status_code}` : ""}${call.refusal_reason ? ` · ${call.refusal_reason}` : ""}`,
            ],
            ["Tokens", `${call.tokens_in} in → ${call.tokens_out} out · ${call.latency_ms} ms`],
            [
              "Cache",
              call.cache_hit
                ? call.single_flight
                  ? "hit after waiting on an identical request (single-flight)"
                  : "hit"
                : "miss",
            ],
            [
              "Job",
              call.job_id ? (
                <Link
                  key="j"
                  className="text-primary underline"
                  to={`/admin/debug/jobs/${call.job_id}`}
                >
                  {call.job_id.slice(0, 8)} · attempt {call.attempt}
                </Link>
              ) : (
                "—"
              ),
            ],
            [
              "Request hash",
              <code key="h" className="break-all">
                {call.request_hash ?? "—"}
              </code>,
            ],
          ]}
        />
      </Section>
      <Section title="Trace">
        {trace ? <TraceView t={trace} /> : <p className="text-small">{tracing_note}</p>}
      </Section>
      {repair && (
        <Section title={`JSON repair call #${repair.id}`}>
          <p className="mb-2 text-small">
            {repair.status_code === 200
              ? "Repair call answered"
              : `Repair call failed (${repair.status_code})`}{" "}
            · {repair.tokens_in} → {repair.tokens_out} tokens
          </p>
          {repair.trace && <TraceView t={repair.trace} />}
        </Section>
      )}
      {trace && replay && <ReplayPanel callId={call.id} trace={trace} avail={replay} />}
    </div>
  );
}

function ReplayPanel({
  callId,
  trace,
  avail,
}: {
  callId: number;
  trace: Trace;
  avail: NonNullable<CallDetail["replay"]>;
}) {
  const [target, setTarget] = useState(avail.targets[0] ?? "mock");
  const [draft, setDraft] = useState(() => JSON.stringify(trace.messages ?? [], null, 2));
  const [jobId, setJobId] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: (messages: unknown) =>
      adminCall<{ job_id: string }>(`/api/admin/debug/calls/${callId}/replay`, {
        method: "POST",
        body: { target, messages },
      }),
    onSuccess: (r) => setJobId(r.job_id),
  });
  const res = useQuery({
    queryKey: ["admin", "debug", "replay", jobId],
    queryFn: () => adminCall<ReplayResult>(`/api/admin/debug/replays/${jobId}`),
    enabled: jobId !== null,
    refetchInterval: (q) =>
      q.state.data && ["done", "failed", "cancelled"].includes(q.state.data.status) ? false : 1500,
  });
  if (!avail.available)
    return (
      <Section title="Replay">
        <p role="status" className="text-small">
          Replay is unavailable here. {avail.reason}
        </p>
      </Section>
    );
  const run = () => {
    setParseError(null);
    try {
      const edited = JSON.parse(draft) as unknown;
      const same = draft === JSON.stringify(trace.messages ?? [], null, 2);
      start.mutate(same ? null : edited);
    } catch {
      setParseError("The messages are not valid JSON.");
    }
  };
  const r = res.data;
  return (
    <Section title="Replay (mock or local only)">
      <div className="flex flex-col gap-3 text-small">
        <p>
          Runs this prompt again as a job, never on the platform and never through the class cache.
          The call is logged as a replay and left out of every number.
        </p>
        <Field label="Target">
          <select className={inputClass} value={target} onChange={(e) => setTarget(e.target.value)}>
            {avail.targets.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Messages (edit to try a different prompt)">
          <textarea
            className={cx(inputClass, "min-h-60 font-mono")}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </Field>
        <ErrorNote error={parseError ?? start.error} />
        <SmallButton
          tone="primary"
          disabled={start.isPending || (r !== undefined && !["done", "failed"].includes(r.status))}
          onClick={run}
        >
          Replay
        </SmallButton>
        {jobId && (
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <h3 className="font-semibold">Original reply</h3>
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-soft border-2 border-sand bg-whitewash p-2">
                {trace.reply ?? "—"}
              </pre>
            </div>
            <div>
              <h3 className="font-semibold">
                Replay{" "}
                {r
                  ? `(${r.status}${r.result ? `, ${r.result.model_tier} on ${r.result.target}, ${r.result.latency_ms} ms` : ""})`
                  : "(queued)"}
              </h3>
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-soft border-2 border-sand bg-whitewash p-2">
                {r?.result
                  ? typeof r.result.content === "string"
                    ? r.result.content
                    : JSON.stringify(r.result.content, null, 2)
                  : r?.error
                    ? plainError(r.error)
                    : "…"}
              </pre>
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}

// --- routing check -------------------------------------------------------------------------------
function RoutingPage() {
  const [hours, setHours] = useState(24);
  const [provider, setProvider] = useState("all");
  const q = useDebug<Routing>(`/api/admin/debug/routing?hours=${hours}&provider=${provider}`, true);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Window">
          <select
            className={inputClass}
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          >
            {[1, 6, 24, 72, 168].map((h) => (
              <option key={h} value={h}>
                last {h} h
              </option>
            ))}
          </select>
        </Field>
        <Field label="Provider">
          <select
            className={inputClass}
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            {["all", "cloud", "local", "mock"].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </Field>
      </div>
      {!q.data ? (
        <Loading q={q} />
      ) : (
        <>
          <p className="text-small">
            {q.data.flags === 0 ? (
              <Pill tone="on">No routing problem in this window</Pill>
            ) : (
              <Pill tone="warn">{q.data.flags} to look at</Pill>
            )}{" "}
            Cache hits and replays are left out. Mid calls on a compact task are flagged unless the
            task escalates by design (Tutor).
          </p>
          <Section title="Calls by task, next to the routing table">
            <DataTable
              rows={q.data.kinds}
              rowKey={(k) => k.task_kind}
              columns={[
                {
                  label: "Task",
                  render: (k) => <span className="font-semibold">{k.task_kind}</span>,
                },
                {
                  label: "Table says",
                  render: (k) => (k.expected ? `${k.expected.tier} · ${k.expected.pattern}` : "—"),
                },
                {
                  label: "Actual",
                  render: (k) =>
                    k.actual.length === 0 ? (
                      "no calls"
                    ) : (
                      <ul className="flex flex-col gap-1">
                        {k.actual.map((a) => (
                          <li key={`${a.tier}${a.pattern}`}>
                            {a.tier} · {a.pattern}: {a.calls}{" "}
                            {a.flag && (
                              <Pill tone={a.flag === "fallback" ? "neutral" : "warn"}>
                                {a.flag.replaceAll("_", " ")}
                              </Pill>
                            )}
                          </li>
                        ))}
                      </ul>
                    ),
                },
              ]}
            />
          </Section>
          <Section title={`Repeated identical requests (${q.data.repeats.length})`}>
            <DataTable
              rows={q.data.repeats}
              rowKey={(r) => r.request_hash}
              empty="None: every successful request was answered once."
              columns={[
                { label: "Task", render: (r) => r.task_kind },
                { label: "Calls", render: (r) => r.calls },
                {
                  label: "First → last",
                  render: (r) => `${when(r.first)} → ${when(r.last).slice(11)}`,
                },
                {
                  label: "Cache purge between",
                  render: (r) => (r.purge_between ? "yes (expected)" : <Pill tone="warn">no</Pill>),
                },
                {
                  label: "Calls",
                  render: (r) => (
                    <span className="flex flex-wrap gap-1">
                      {r.call_ids.map((c) => (
                        <Link
                          key={c}
                          className="text-primary underline"
                          to={`/admin/debug/calls/${c}`}
                        >
                          #{c}
                        </Link>
                      ))}
                    </span>
                  ),
                },
              ]}
            />
          </Section>
        </>
      )}
    </div>
  );
}
