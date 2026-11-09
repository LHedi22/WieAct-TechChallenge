// Runtime switches (backend core/flags.py): applied by the API and the worker within ~3 s.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { cx } from "@/components/cx";
import { adminApi, type Switch, type SwitchKey, type Switches } from "./adminApi";
import { inputClass, when } from "./format";
import { ErrorNote, Field, Pill, Section, SmallButton, Toggle } from "./ui";

const QUICK_MINUTES = [5, 10, 15, 30, 60];

export function SwitchesPage() {
  const q = useQuery({
    queryKey: ["admin", "switches"],
    queryFn: adminApi.switches,
    refetchInterval: 10_000,
  });
  if (q.isPending) return <p className="text-small">Loading switches…</p>;
  if (q.error) return <ErrorNote error={q.error} />;
  return <SwitchList data={q.data} />;
}

function SwitchList({ data }: { data: Switches }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const set = useMutation({
    mutationFn: ({ key, value }: { key: SwitchKey; value: unknown }) =>
      adminApi.setSwitch(key, value, reason),
    onSuccess: (next) => {
      qc.setQueryData(["admin", "switches"], next);
      setReason("");
    },
  });
  const by = Object.fromEntries(data.switches.map((s) => [s.key, s])) as Record<SwitchKey, Switch>;
  const change = (key: SwitchKey, value: unknown) => set.mutate({ key, value });
  const busy = set.isPending;

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <header className="flex flex-col gap-2">
        <h1 className="font-heading text-h2">Switches</h1>
        <p className="text-small text-ink/80">
          Changes apply to the API and the worker within about 3 seconds, without a restart. Every
          change is written to the admin log.
        </p>
        <div className="flex flex-wrap gap-2 text-small">
          <Pill>env: {data.app_env}</Pill>
          <Pill>provider now: {data.provider}</Pill>
          <Pill>configured: {data.configured_provider}</Pill>
          {data.offline_now && <Pill tone="warn">AI paused (offline demo mode)</Pill>}
        </div>
      </header>

      <Field label="Reason (optional, saved with the next change)">
        <input
          className={inputClass}
          value={reason}
          maxLength={500}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. recording the fallback shot"
        />
      </Field>
      <ErrorNote error={set.error} />

      <SwitchCard
        s={by.force_quick_mode}
        title="Force Quick mode"
        what="Interactive mid-size tasks are answered by the compact model with the Quick mode badge. Real calls, logged as forced and counted apart from real fallbacks in Stats. Turns itself off."
        state={
          by.force_quick_mode.effective ? (
            <Pill tone="on">
              On
              {typeof by.force_quick_mode.value === "string" &&
                ` until ${when(by.force_quick_mode.value)}`}
            </Pill>
          ) : (
            <Pill>Off</Pill>
          )
        }
      >
        <QuickControls
          on={Boolean(by.force_quick_mode.effective)}
          max={data.force_quick_max_minutes}
          busy={busy}
          onChange={(minutes) => change("force_quick_mode", minutes)}
        />
      </SwitchCard>

      <SwitchCard
        s={by.offline_demo_mode}
        title="Offline demo mode"
        what="On: new AI actions pause with a banner, saved results keep working. Auto: the environment decides (outside our slot in production)."
        state={
          <Pill tone={by.offline_demo_mode.effective === "on" ? "warn" : "neutral"}>
            {String(by.offline_demo_mode.effective)}
          </Pill>
        }
      >
        <div role="radiogroup" aria-label="Offline demo mode" className="flex flex-wrap gap-2">
          {(["auto", "on", "off"] as const).map((v) => {
            const selected = (by.offline_demo_mode.value ?? "auto") === v;
            return (
              <button
                key={v}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={busy}
                onClick={() => change("offline_demo_mode", v)}
                className={cx(
                  "min-h-11 rounded-soft border-2 px-4 text-small font-semibold",
                  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sea",
                  selected ? "border-primary-dark bg-primary text-white" : "border-ink bg-white",
                )}
              >
                {v}
              </button>
            );
          })}
        </div>
      </SwitchCard>

      <SwitchCard
        s={by.pause_background_lane}
        title="Pause background lane"
        what="The worker starts no background job (tagging, indexing, tips, daily plans, quiz pools). Students' interactive jobs still run; running jobs finish."
        state={
          <Pill tone={by.pause_background_lane.effective ? "warn" : "neutral"}>
            {by.pause_background_lane.effective ? "Paused" : "Running"}
          </Pill>
        }
      >
        <div className="flex items-center gap-3">
          <Toggle
            label="Pause background lane"
            checked={Boolean(by.pause_background_lane.effective)}
            disabled={busy}
            onChange={(next) => change("pause_background_lane", next)}
          />
          <span className="text-small">
            {by.pause_background_lane.effective ? "Paused" : "Not paused"}
          </span>
        </div>
      </SwitchCard>

      <SwitchCard
        s={by.llm_max_rpm_override}
        title="Lower the request rate"
        what={`Requests per minute the gateway sends. May only lower the configured ${data.llm_max_rpm}, never raise it.`}
        state={<Pill>{String(by.llm_max_rpm_override.effective)} / min</Pill>}
      >
        <RpmControls
          max={data.llm_max_rpm}
          current={
            typeof by.llm_max_rpm_override.value === "number" ? by.llm_max_rpm_override.value : null
          }
          busy={busy}
          onChange={(v) => change("llm_max_rpm_override", v)}
        />
      </SwitchCard>
    </div>
  );
}

function SwitchCard({
  s,
  title,
  what,
  state,
  children,
}: {
  s: Switch;
  title: string;
  what: string;
  state: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Section title={title} actions={state}>
      <p className="mb-3 text-small text-ink/80">{what}</p>
      {children}
      <p className="mt-3 text-small text-ink/70">
        {s.updated_at
          ? `Changed by ${s.updated_by ?? "?"} · ${when(s.updated_at)}`
          : "Never changed"}
        {s.env_note && ` · ${s.env_note}`}
      </p>
    </Section>
  );
}

function QuickControls({
  on,
  max,
  busy,
  onChange,
}: {
  on: boolean;
  max: number;
  busy: boolean;
  onChange: (minutes: number) => void;
}) {
  const [minutes, setMinutes] = useState(10);
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Field label="For">
        <select
          className={inputClass}
          value={minutes}
          onChange={(e) => setMinutes(Number(e.target.value))}
        >
          {QUICK_MINUTES.filter((m) => m <= max).map((m) => (
            <option key={m} value={m}>
              {m} minutes
            </option>
          ))}
        </select>
      </Field>
      <SmallButton tone="primary" disabled={busy} onClick={() => onChange(minutes)}>
        {on ? "Restart timer" : "Turn on"}
      </SmallButton>
      <SmallButton disabled={busy || !on} onClick={() => onChange(0)}>
        Turn off
      </SmallButton>
    </div>
  );
}

function RpmControls({
  max,
  current,
  busy,
  onChange,
}: {
  max: number;
  current: number | null;
  busy: boolean;
  onChange: (v: number | null) => void;
}) {
  const [value, setValue] = useState(String(current ?? max));
  const n = Number(value);
  const valid = Number.isInteger(n) && n >= 1 && n <= max;
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Field label={`Requests per minute (1–${max})`}>
        <input
          type="number"
          min={1}
          max={max}
          className={cx(inputClass, "w-28")}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </Field>
      <SmallButton tone="primary" disabled={busy || !valid} onClick={() => onChange(n)}>
        Apply
      </SmallButton>
      <SmallButton disabled={busy || current === null} onClick={() => onChange(null)}>
        Back to {max}
      </SmallButton>
    </div>
  );
}
