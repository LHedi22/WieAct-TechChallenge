// Shared bits of /admin/debug (hooks, constants, table columns): no components exported here.
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { adminCall } from "./adminApi";
import type { CallRow, Outcome } from "./debugTypes";
import { when } from "./format";
import type { Column } from "./table";
import { Pill } from "./ui";

export const POLL_MS = 2500;

export function useDebug<T>(path: string, poll = false) {
  return useQuery({
    queryKey: ["admin", "debug", path],
    queryFn: () => adminCall<T>(path),
    refetchInterval: poll ? POLL_MS : false,
    refetchIntervalInBackground: false,
  });
}

// each square also carries a letter: never colour alone
export const OUTCOME: Record<Outcome, { cls: string; letter: string; label: string }> = {
  ok: { cls: "bg-olive-ink text-white", letter: "✓", label: "ok" },
  cache: { cls: "bg-sea-ink text-white", letter: "C", label: "cache hit" },
  "503": { cls: "bg-terracotta-ink text-white", letter: "5", label: "503 saturated" },
  quota: { cls: "bg-terracotta-light text-ink", letter: "Q", label: "quota" },
  "400": { cls: "bg-danger text-white", letter: "4", label: "400 ceiling" },
  fallback: { cls: "bg-primary text-white", letter: "F", label: "fallback (Quick mode)" },
  forced: {
    cls: "border-2 border-dashed border-primary bg-white text-ink",
    letter: "f",
    label: "forced fallback",
  },
  repair: { cls: "bg-sand text-ink", letter: "R", label: "JSON repair" },
  error: { cls: "bg-ink text-white", letter: "!", label: "other error" },
};

export const callColumns: Column<CallRow>[] = [
  {
    label: "Call",
    render: (c) => (
      <Link className="font-semibold text-primary underline" to={`/admin/debug/calls/${c.id}`}>
        #{c.id}
      </Link>
    ),
  },
  { label: "Time", render: (c) => when(c.ts).slice(11) },
  { label: "Task", render: (c) => c.task_kind },
  { label: "Tier", render: (c) => c.tier },
  { label: "Pattern", render: (c) => c.pattern },
  { label: "Attempt", render: (c) => c.attempt ?? "—" },
  {
    label: "Status",
    render: (c) => (
      <Pill tone={c.status_code === 200 || c.cache_hit ? "on" : "warn"}>
        {OUTCOME[c.outcome]?.label ?? c.outcome}
        {c.status_code && c.status_code !== 200 ? ` (${c.status_code})` : ""}
      </Pill>
    ),
  },
  { label: "Tokens", render: (c) => `${c.tokens_in} → ${c.tokens_out}` },
  { label: "Latency", render: (c) => `${c.latency_ms} ms` },
  {
    label: "Notes",
    render: (c) =>
      [
        c.cache_hit && (c.single_flight ? "single-flight follower" : "cache hit"),
        c.traced && "traced",
        c.debug && "replay",
      ]
        .filter(Boolean)
        .join(" · ") || "—",
  },
];
