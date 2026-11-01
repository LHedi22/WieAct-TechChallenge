import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { WisdomTip } from "@/api/client";
import { Bidi, MathText, SoftCard } from "@/components";
import { useClassTips } from "./useWisdomTip";

const GENERAL_TIPS = 6;

/** One anonymous Class Wisdom tip (trap → why → right) with "Show me another tip". */
export function WisdomTipBody({ tips }: { tips: WisdomTip[] }) {
  const { t } = useTranslation();
  const [i, setI] = useState(0);
  const tip = tips[i % tips.length];
  if (!tip) return null;
  return (
    <div className="flex flex-col gap-2" data-testid="wisdom-tip">
      <p>
        <strong>
          {t("wisdom.classmates", { count: tip.student_count })} <MathText text={tip.trap} />
        </strong>{" "}
        <MathText text={tip.why} />
      </p>
      <p>
        <MathText text={tip.right} />
      </p>
      <p className="rounded-soft bg-sand/40 px-3 py-2 text-small text-ink/70">
        {t("wisdom.anonymous")}
      </p>
      {tips.length > 1 && (
        <button
          type="button"
          className="self-start text-small font-semibold text-primary underline"
          onClick={() => setI((n) => n + 1)}
        >
          {t("wisdom.another")}{" "}
          <span className="text-ink/70">
            (<Bidi>{`${(i % tips.length) + 1}/${tips.length}`}</Bidi>)
          </span>
        </button>
      )}
    </div>
  );
}

/** A general study tip (no AI, no classmates' data), for a course with no Class Wisdom yet. */
export function GeneralTip() {
  const { t } = useTranslation();
  const [i, setI] = useState(() => Math.floor(Math.random() * GENERAL_TIPS));
  return (
    <div className="flex flex-col gap-2" data-testid="general-tip">
      <p>{t(`wisdom.general.tips.${(i % GENERAL_TIPS) + 1}`)}</p>
      <button
        type="button"
        className="self-start text-small font-semibold text-primary underline"
        onClick={() => setI((n) => n + 1)}
      >
        {t("wisdom.another")}
      </button>
    </div>
  );
}

/** A standalone Class Wisdom card (Quiz Hall results): this course's tips only, else nothing. */
export function WisdomCard({ worldId, courseId }: { worldId: string; courseId?: string }) {
  const { t } = useTranslation();
  const tips = useClassTips(worldId, courseId);
  if (!tips.length) return null;
  return (
    <SoftCard className="flex flex-col gap-2 bg-sand/20">
      <h2 className="text-h3 text-olive-ink">{t("wisdom.title")}</h2>
      <WisdomTipBody tips={tips} />
    </SoftCard>
  );
}
