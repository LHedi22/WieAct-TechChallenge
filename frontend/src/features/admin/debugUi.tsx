// Small display components of /admin/debug.
import { useState, type ReactNode } from "react";
import { Json } from "./table";
import { ErrorNote, SmallButton } from "./ui";

export function Loading({ q }: { q: { isPending: boolean; error: unknown } }) {
  if (q.error) return <ErrorNote error={q.error} />;
  return q.isPending ? <p className="text-small">Loading…</p> : null;
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-small">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="font-semibold text-ink/80">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Raw({ value, label = "Raw JSON" }: { value: unknown; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <SmallButton onClick={() => setOpen(!open)}>{open ? `Hide ${label}` : label}</SmallButton>
      {open && <Json value={value} />}
    </div>
  );
}
