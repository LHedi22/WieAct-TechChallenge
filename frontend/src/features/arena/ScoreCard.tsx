import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Bidi, Chip, ProgressBar } from "@/components";
import { useNumberFormat } from "@/components/useNumberFormat";

/** One "thing to fix" as the API sends it: {quote, fix}. */
export type Fix = Partial<Record<"quote" | "fix", string>>;

/** The explanation with each quoted mistake underlined (quotes are copied from the text). */
export function Highlighted({ text, quotes }: { text: string; quotes: string[] }) {
  const parts: ReactNode[] = [];
  let rest = text;
  let key = 0;
  for (;;) {
    const hits = quotes
      .filter((q) => q.trim())
      .map((q) => ({ q, at: rest.indexOf(q) }))
      .filter((h) => h.at >= 0)
      .sort((a, b) => a.at - b.at);
    const hit = hits[0];
    if (!hit) break;
    parts.push(rest.slice(0, hit.at));
    parts.push(
      <mark
        key={key++}
        className="bg-transparent text-inherit underline decoration-danger decoration-2 underline-offset-4"
      >
        {hit.q}
      </mark>,
    );
    rest = rest.slice(hit.at + hit.q.length);
  }
  parts.push(rest);
  return <p className="whitespace-pre-line">{parts}</p>;
}

/** Score /100, confidence, "things to fix", the "Good:" line and what was missing. */
export function ScoreCard({
  score,
  confidence,
  text,
  errors,
  good,
  missing,
  quickMode,
}: {
  score: number;
  confidence: string | null;
  text: string;
  errors: Fix[];
  good: string;
  missing: string[];
  quickMode?: boolean;
}) {
  const { t } = useTranslation("arena");
  const { t: tc } = useTranslation();
  const nf = useNumberFormat();
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <p>
          <span className="font-heading text-[2.5rem] leading-none">
            <Bidi>{nf.format(score)}</Bidi>
          </span>
          <span className="text-ink/70"> {t("outOf")}</span>
        </p>
        <ProgressBar value={score} max={100} label={t("scoreLabel")} className="min-w-40 flex-1" />
        {confidence && (
          <Chip kind="confidence">
            {tc("chip.confidence", { level: tc(`confidence.${confidence}`) })}
          </Chip>
        )}
        {quickMode && <Chip kind="quickMode">{tc("chip.quickMode")}</Chip>}
      </div>
      <Highlighted text={text} quotes={errors.map((e) => e.quote ?? "")} />
      {errors.length > 0 && (
        <div className="rounded-soft bg-danger/10 p-3">
          <p className="font-semibold text-danger">{t("toFix", { count: errors.length })}</p>
          <ul className="mt-1 flex list-disc flex-col gap-1 ps-5">
            {errors.map((e, i) => (
              <li key={i}>{e.fix}</li>
            ))}
          </ul>
        </div>
      )}
      {good && (
        <p className="text-olive-ink">
          <span aria-hidden="true">✓ </span>
          {t("good", { text: good })}
        </p>
      )}
      {missing.length > 0 && (
        <p className="text-small text-ink/70">{t("missing", { ideas: missing.join(" · ") })}</p>
      )}
    </div>
  );
}
