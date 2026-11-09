// /api/admin/stats: the numbers the organisers compute on our key. Defaults to provider=cloud.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { cx } from "@/components/cx";
import { adminApi, type Stats } from "./adminApi";
import { inputClass } from "./format";
import { ErrorNote, Field, Section } from "./ui";

const PROVIDERS = ["cloud", "local", "mock", "all"] as const;

export function StatsPage() {
  const [provider, setProvider] = useState<(typeof PROVIDERS)[number]>("cloud");
  const q = useQuery({
    queryKey: ["admin", "stats", provider],
    queryFn: () => adminApi.stats(provider),
    refetchInterval: 15_000,
  });
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="font-heading text-h2">Stats</h1>
        <Field label="Provider">
          <select
            className={cx(inputClass, "w-36")}
            value={provider}
            onChange={(e) => setProvider(e.target.value as (typeof PROVIDERS)[number])}
          >
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </Field>
      </header>
      {q.isPending ? (
        <p className="text-small">Loading…</p>
      ) : q.error ? (
        <ErrorNote error={q.error} />
      ) : (
        <StatsView s={q.data} />
      )}
    </div>
  );
}

function Metric({ label, value, note }: { label: string; value: string | number; note?: string }) {
  return (
    <div className="rounded-soft border-2 border-sand bg-white p-3">
      <div className="text-small text-ink/70">{label}</div>
      <div className="font-heading text-h3">{value}</div>
      {note && <div className="text-small text-ink/70">{note}</div>}
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-start text-small">
        <thead>
          <tr className="border-b-2 border-sand">
            {head.map((h) => (
              <th
                key={h}
                scope="col"
                className="whitespace-nowrap px-2 py-1 text-start font-semibold"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-sand/60">
              {r.map((c, j) => (
                <td key={j} className="px-2 py-1 tabular-nums">
                  {c}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={head.length} className="px-2 py-2 text-ink/70">
                Nothing yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function StatsView({ s }: { s: Stats }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label="Calls (incl. retries)" value={s.calls} note={`${s.ok} answered 200`} />
        <Metric
          label="Compact share"
          value={`${Math.round(s.compact_share * 100)}%`}
          note="of chat calls"
        />
        <Metric label="Served from cache" value={s.cache_hits} note="no call made" />
        <Metric label="Repeated identical" value={s.repeated_identical} note="keep near 0" />
        <Metric label="Real fallbacks" value={s.fallbacks} note="caused by the platform" />
        <Metric
          label="Forced Quick mode"
          value={s.forced_fallbacks}
          note="admin switch, not a fallback"
        />
      </div>
      <Section title="By tier">
        <Table
          head={["Tier", "Calls", "Tokens in", "Tokens out", "Avg latency"]}
          rows={Object.entries(s.by_tier).map(([t, v]) => [
            t,
            v.calls,
            v.tokens_in,
            v.tokens_out,
            `${(v.avg_latency_ms / 1000).toFixed(1)} s`,
          ])}
        />
      </Section>
      <div className="grid gap-4 md:grid-cols-2">
        <Section title="By task">
          <Table
            head={["Task", "Calls"]}
            rows={Object.entries(s.by_task).sort((a, b) => b[1] - a[1])}
          />
        </Section>
        <Section title="Refusals handled">
          <Table head={["Reason", "Count"]} rows={Object.entries(s.refusals)} />
        </Section>
      </div>
      <p className="text-small text-ink/70">
        Quota headers seen:{" "}
        {s.quota_headers_seen.length ? s.quota_headers_seen.join(", ") : "none yet"}
      </p>
    </>
  );
}
