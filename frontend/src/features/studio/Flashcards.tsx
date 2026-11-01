import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type CardGrade, type CardQueue, type StudyCard } from "@/api/client";
import { MathText, PixelButton, PixelPanel, ProgressBar, SoftCard } from "@/components";
import { cx } from "@/components/cx";
import { ErrorBanner } from "@/features/worlds/parts";
import { cardsKey, useWhen } from "./cards";

const GRADES: { grade: CardGrade; key: string; variant: "secondary" | "success" | "primary" }[] = [
  { grade: "again", key: "1", variant: "secondary" },
  { grade: "good", key: "2", variant: "success" },
  { grade: "easy", key: "3", variant: "primary" },
];

function Legend({ counts }: { counts: CardQueue["counts"] }) {
  const { t } = useTranslation("studio");
  const items = [
    { k: "new", n: counts.new, dot: "bg-primary" },
    { k: "learning", n: counts.learning, dot: "bg-terracotta" },
    { k: "review", n: counts.review, dot: "bg-olive" },
  ] as const;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-small">
      {items.map((i) => (
        <li key={i.k} className="flex items-center gap-1.5">
          <span aria-hidden className={cx("size-3", i.dot)} />
          {t(`counts.${i.k}`, { count: i.n })}
        </li>
      ))}
    </ul>
  );
}

/** Spaced-repetition review (mockup 16): the card flips with Space, 1/2/3 grade it, and each
 * button shows when the card comes back (from the server's schedule). Reviews are free. */
export function Flashcards({ chapterId, level }: { chapterId: string; level: string }) {
  const { t } = useTranslation("studio");
  const qc = useQueryClient();
  const when = useWhen();
  const q = useQuery({
    queryKey: cardsKey(chapterId, level),
    queryFn: () => api.studioCards(chapterId, level),
  });
  // Cards graded in this sitting, with when they are due again: they leave the round until then.
  const [dueAt, setDueAt] = useState<Record<string, number>>({});
  const [now, setNow] = useState(() => Date.now());
  const [flipped, setFlipped] = useState(false);
  const cards = q.data?.cards ?? [];
  const left = cards.filter((c) => (dueAt[c.id] ?? 0) <= now);
  const card: StudyCard | undefined = left[0];

  const review = useMutation({
    mutationFn: ({ id, grade }: { id: string; grade: CardGrade }) => api.reviewCard(id, grade),
    onSuccess: (r) => {
      setDueAt((d) => ({ ...d, [r.card_id]: Date.parse(r.due_at) }));
      setFlipped(false);
      void qc.invalidateQueries({ queryKey: ["daily"] });
    },
  });
  const grade = useCallback(
    (g: CardGrade) => {
      if (card && flipped && !review.isPending) review.mutate({ id: card.id, grade: g });
    },
    [card, flipped, review],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el?.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === " " && card) {
        e.preventDefault();
        setFlipped((f) => !f);
      }
      const g = GRADES.find((x) => x.key === e.key);
      if (g) grade(g.grade);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [card, grade]);

  const more = () => {
    setNow(Date.now());
    void q.refetch();
  };

  if (!q.data) return <ErrorBanner error={q.error} />;
  const total = cards.length;
  if (!card) {
    const next = q.data.next_due_at ? Date.parse(q.data.next_due_at) - now : null;
    return (
      <SoftCard className="flex flex-col items-start gap-3" data-testid="cards-done">
        <h2 className="text-h2">{total ? t("done.round", { count: total }) : t("done.title")}</h2>
        {next !== null && next > 0 && <p>{t("done.next", { when: when(next / 1000) })}</p>}
        <PixelButton variant="secondary" onClick={more}>
          {t("done.more")}
        </PixelButton>
      </SoftCard>
    );
  }
  const n = total - left.length + 1;

  return (
    <section className="flex flex-col gap-4" aria-label={t("tabs.flashcards")}>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <p className="font-heading text-h3">{t("cardOf", { n, total })}</p>
        <ProgressBar
          value={n - 1}
          max={total}
          label={t("cardOf", { n, total })}
          className="min-w-40 flex-1"
        />
        <Legend counts={q.data.counts} />
      </div>
      <PixelPanel className="flex min-h-64 flex-col gap-4 p-6 sm:p-10" data-testid="flashcard">
        <p className={cx(flipped ? "text-ink/70" : "text-h2 font-heading")} dir="auto">
          <MathText text={card.front} />
        </p>
        {flipped ? (
          <>
            <hr className="border-t-2 border-sand" />
            <p className="text-small font-semibold text-primary">{t("answer")}</p>
            <p className="whitespace-pre-line text-h3" dir="auto">
              <MathText text={card.back} />
            </p>
          </>
        ) : (
          <PixelButton
            variant="secondary"
            className="mt-auto self-center"
            onClick={() => setFlipped(true)}
          >
            {t("show")}
          </PixelButton>
        )}
      </PixelPanel>
      {flipped && (
        <div className="flex flex-col gap-2">
          <p className="text-center font-semibold">{t("howWell")}</p>
          <div className="grid grid-cols-3 gap-3">
            {GRADES.map((g) => (
              <PixelButton
                key={g.grade}
                variant={g.variant}
                disabled={review.isPending}
                onClick={() => grade(g.grade)}
                className="flex flex-col items-center py-2"
              >
                <span>{t(`grade.${g.grade}`)}</span>
                <span className="text-small font-normal">{when(card.intervals[g.grade] ?? 0)}</span>
              </PixelButton>
            ))}
          </div>
        </div>
      )}
      <p className="text-center text-small text-ink/70">{t("keys")}</p>
      <ErrorBanner error={review.error} />
    </section>
  );
}
