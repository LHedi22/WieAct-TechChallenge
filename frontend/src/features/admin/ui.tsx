// Small, calm building blocks for the admin side: plain and dense, no pixel world.
import type { ReactNode } from "react";
import { cx } from "@/components/cx";

export function Section({
  title,
  actions,
  children,
  className,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cx("rounded-soft border-2 border-sand bg-white p-4", className)}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-heading text-h3">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function SmallButton({
  children,
  onClick,
  disabled,
  tone = "default",
  type = "button",
  ariaLabel,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  tone?: "default" | "primary" | "danger";
  type?: "button" | "submit";
  ariaLabel?: string;
}) {
  const tones = {
    default: "border-ink bg-white text-ink hover:bg-whitewash",
    primary: "border-primary-dark bg-primary text-white hover:bg-primary-dark",
    danger: "border-danger bg-white text-danger hover:bg-danger hover:text-white",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      className={cx(
        "min-h-11 rounded-soft border-2 px-3 py-1.5 text-small font-semibold",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sea",
        disabled ? "cursor-not-allowed border-ink/20 bg-sand/30 text-ink/50" : tones[tone],
      )}
    >
      {children}
    </button>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative inline-flex h-8 w-14 shrink-0 items-center rounded-full border-2 border-ink transition-colors",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sea",
        checked ? "bg-olive-ink" : "bg-sand/60",
        disabled && "opacity-50",
      )}
    >
      <span
        aria-hidden
        className={cx(
          "inline-block h-5 w-5 rounded-full border-2 border-ink bg-white transition-transform",
          checked ? "translate-x-7 rtl:-translate-x-7" : "translate-x-1 rtl:-translate-x-1",
        )}
      />
    </button>
  );
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-small">
      <span className="font-semibold">{label}</span>
      {children}
      {hint && <span className="text-ink/70">{hint}</span>}
    </label>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <p
      role="alert"
      className="rounded-soft border-2 border-danger bg-white px-3 py-2 text-small text-danger"
    >
      {message}
    </p>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "on" | "warn";
}) {
  const tones = {
    neutral: "border-ink/30 bg-whitewash text-ink",
    on: "border-olive-ink bg-olive-light/30 text-olive-ink",
    warn: "border-terracotta-ink bg-terracotta-light/25 text-terracotta-ink",
  };
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-small font-semibold",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}
