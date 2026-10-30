import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type IslandOut } from "@/api/client";
import { Bidi, Chip, PixelButton, PixelPanel } from "@/components";
import { cx } from "@/components/cx";
import { useNumberFormat } from "@/components/useNumberFormat";
import { useWallet } from "@/hooks/useSession";

export type Level = "beginner" | "intermediate" | "advanced";
const LEVELS: Level[] = ["beginner", "intermediate", "advanced"];
type Building = IslandOut["buildings"][number];

/** Building entry dialog: chapter + level, cost and balance after, Confirm (PRODUCT.md screen 8).
 * Costs come from the island payload, which comes from economy.py. */
export function BuildingDialog({
  island,
  building,
  onClose,
  onConfirm,
}: {
  island: IslandOut;
  building: Building;
  onClose: () => void;
  onConfirm: (chapterId: string, level: Level) => void;
}) {
  const { t } = useTranslation("island");
  const { t: tc } = useTranslation();
  const wallet = useWallet().data;
  const nf = useNumberFormat();
  const ready = island.chapters.filter((c) => c.ready);
  const [chapterId, setChapterId] = useState(ready[0]?.id ?? island.chapters[0]?.id ?? "");
  const [level, setLevel] = useState<Level>((island.level as Level | null) ?? "intermediate");
  const titleId = useId();
  const selectId = useId();
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panel.current?.querySelector<HTMLElement>("select, button")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Quiz Hall, Study Studio and Audio Studio ask the server before Confirm: free when the class
  // already made it (an unseen quiz set, the study pack, the episode) — DESIGN.md fix 2, ECONOMY.md.
  const PRICES: Record<
    string,
    (chapter: string, level: string) => Promise<{ cost: number; cached: boolean }>
  > = {
    quiz_hall: api.quizPrice,
    study_studio: api.studioPrice,
    audio_studio: api.audioPrice,
  };
  const priceOf = PRICES[building.key];
  const priced = !!priceOf;
  const livePrice = useQuery({
    queryKey: [building.key, "price", chapterId, level],
    queryFn: () => priceOf!(chapterId, level),
    enabled: priced && !!chapterId,
  });
  const cost = priced ? (livePrice.data?.cost ?? building.cost) : building.cost;
  const cachedQuiz = priced && livePrice.data?.cached;
  const balance = wallet?.coins ?? 0;
  const after = balance - cost;
  // Answering in the Teach-Back Arena is free: only asking costs, and that is checked on ask.
  const short = after < 0 && building.answer_cost !== 0;

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label={t("dialog.cancel")}
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 bg-ink/40"
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative w-full max-w-md"
      >
        <PixelPanel className="flex flex-col gap-4">
          <h2 id={titleId} className="text-h2">
            {tc(`buildings.${building.key}`)}
          </h2>
          <div className="flex flex-col gap-1">
            <label htmlFor={selectId} className="font-semibold">
              {t("dialog.chapter")}
            </label>
            <select
              id={selectId}
              value={chapterId}
              onChange={(e) => setChapterId(e.target.value)}
              className="min-h-11 rounded-pixel-step border-2 border-ink bg-white px-3"
            >
              {island.chapters.map((c) => (
                <option key={c.id} value={c.id} disabled={!c.ready}>
                  {c.idx} · {c.title}
                </option>
              ))}
            </select>
          </div>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 font-semibold">{t("dialog.level")}</legend>
            <div className="flex flex-wrap gap-2">
              {LEVELS.map((l) => (
                <label
                  key={l}
                  className={cx(
                    "flex min-h-11 cursor-pointer items-center gap-2 rounded-pixel-step border-2 px-3 font-semibold",
                    level === l ? "border-ink bg-primary text-white" : "border-sand bg-white",
                  )}
                >
                  <input
                    type="radio"
                    name="level"
                    value={l}
                    checked={level === l}
                    onChange={() => setLevel(l)}
                    className="sr-only"
                  />
                  <span className="flex flex-col">
                    {tc(`chip.${l}`)}
                    {island.level === l && (
                      <span className="text-small font-normal opacity-80">
                        {t("dialog.fromPlacement")}
                      </span>
                    )}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1">
            <dt>{t("dialog.cost")}</dt>
            <dd className="text-end">
              {building.answer_cost === 0 ? (
                <span className="font-semibold">{t("costs.teachback", { ask: cost })}</span>
              ) : cost === 0 ? (
                <span className="flex flex-col items-end gap-1">
                  <Chip kind="cost">{tc("chip.free")}</Chip>
                  {cachedQuiz && (
                    <span className="text-small text-ink/70">{t("dialog.classMade")}</span>
                  )}
                </span>
              ) : (
                <Chip kind="cost">{tc("chip.cost", { count: cost })}</Chip>
              )}
            </dd>
            <dt>{t("dialog.balanceAfter")}</dt>
            <dd className={cx("text-end font-semibold", short && "text-danger")}>
              <Bidi>{nf.format(Math.max(after, 0))}</Bidi>{" "}
              {tc("counters.coins", { count: Math.max(after, 0) })}
            </dd>
          </dl>
          {short && <p className="text-small text-danger">{t("dialog.short")}</p>}
          <div className="flex justify-end gap-3">
            <PixelButton variant="secondary" onClick={onClose}>
              {t("dialog.cancel")}
            </PixelButton>
            <PixelButton
              variant="spend"
              disabled={short || !chapterId}
              onClick={() => onConfirm(chapterId, level)}
            >
              {t("dialog.confirm")}
            </PixelButton>
          </div>
        </PixelPanel>
      </div>
    </div>
  );
}
