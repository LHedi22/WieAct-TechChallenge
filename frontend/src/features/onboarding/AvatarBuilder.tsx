import { AnimatePresence, motion } from "framer-motion";
import { type KeyboardEvent, type ReactNode, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Avatar,
  type AvatarLook,
  Bidi,
  EXTRAS,
  HAIR_COLORS,
  HAIR_SWATCH,
  HAIRS,
  OUTFIT_SWATCH,
  OUTFITS,
  PixelButton,
  PixelPanel,
  SKIN_SWATCH,
  SKINS,
  Sprite,
} from "@/components";
import { cx } from "@/components/cx";
import { useCalmMotion } from "@/hooks/useCalmMotion";
import { useEconomy } from "@/hooks/useSession";

const TABS = ["hair", "skin", "outfit", "extras"] as const;
type Tab = (typeof TABS)[number];

const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(Math.random() * xs.length)]!;

/** Onboarding step 4: a big live preview, tabs of tap-to-pick tiles that each show the explorer
 * wearing that option, and "Surprise me". Extras priced in points stay locked. */
export function AvatarBuilder({
  nickname,
  look,
  onChange,
  onNext,
  onBack,
}: {
  nickname: string;
  look: AvatarLook;
  onChange: (l: AvatarLook) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const { t } = useTranslation("onboarding");
  const calm = useCalmMotion();
  const cosmetics = useEconomy().data?.cosmetics ?? {};
  const [tab, setTab] = useState<Tab>("hair");
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const free = [null, ...EXTRAS.filter((x) => !(cosmetics[x] ?? 0))];

  const set = (patch: Partial<AvatarLook>) => onChange({ ...look, ...patch });
  const surprise = () => {
    let next = look;
    for (let i = 0; i < 5 && JSON.stringify(next) === JSON.stringify(look); i++) {
      next = {
        skin: pick(SKINS),
        outfit: pick(OUTFITS),
        hair: pick(HAIRS),
        hair_color: pick(HAIR_COLORS),
        extra: pick(free),
      };
    }
    onChange(next);
  };

  const onTabKey = (e: KeyboardEvent, i: number) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (!step) return;
    e.preventDefault();
    const rtl = document.documentElement.dir === "rtl";
    const j = (i + (rtl ? -step : step) + TABS.length) % TABS.length;
    setTab(TABS[j]!);
    tabRefs.current[j]?.focus();
  };

  return (
    <PixelPanel className="order-first flex flex-col gap-5 lg:order-none">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-h2">{t("avatar.title")}</h2>
        <PixelButton variant="secondary" onClick={surprise}>
          <span className="inline-flex items-center gap-2">
            <Sprite name="star" scale={1} />
            {t("avatar.surprise")}
          </span>
        </PixelButton>
      </div>

      <div className="flex flex-col items-center gap-3 rounded-soft border-2 border-ink bg-sea-foam px-4 pb-4 pt-6">
        <motion.div
          animate={calm ? undefined : { y: [0, -4, 0] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
        >
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.div
              key={JSON.stringify(look)}
              initial={calm ? false : { scale: 0.85, rotate: -4 }}
              animate={{ scale: 1, rotate: 0 }}
              transition={{ type: "spring", stiffness: 420, damping: 16 }}
            >
              <Avatar look={look} size={168} label={t("avatar.preview")} />
            </motion.div>
          </AnimatePresence>
        </motion.div>
        <div aria-hidden className="h-2 w-28 rounded-full bg-ink/15" />
        <p className="flex flex-col items-center gap-1 text-center">
          <span className="text-small font-semibold text-ink/70">{t("avatar.nickname")}</span>
          <Bidi className="rounded-pixel-step border-2 border-ink bg-white px-3 py-1 font-heading text-h3">
            {nickname}
          </Bidi>
          <span className="text-small text-ink/70">{t("avatar.nicknameHelp")}</span>
        </p>
      </div>

      <div
        role="tablist"
        aria-label={t("avatar.title")}
        className="grid grid-cols-4 gap-2 sm:flex sm:flex-wrap"
      >
        {TABS.map((k, i) => (
          <button
            key={k}
            ref={(el) => {
              tabRefs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`avatar-tab-${k}`}
            aria-selected={tab === k}
            aria-controls="avatar-panel"
            tabIndex={tab === k ? 0 : -1}
            onClick={() => setTab(k)}
            onKeyDown={(e) => onTabKey(e, i)}
            className={cx(
              "min-h-11 rounded-pixel-step border-2 px-2 font-semibold sm:px-4",
              tab === k ? "border-ink bg-primary text-white" : "border-sand bg-white",
            )}
          >
            {t(`avatar.tabs.${k}`)}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id="avatar-panel"
        aria-labelledby={`avatar-tab-${tab}`}
        className="flex flex-col gap-4"
      >
        {tab === "hair" && (
          <>
            <Tiles legend={t("avatar.hair")}>
              {HAIRS.map((h) => (
                <Tile
                  key={h}
                  label={t(`avatar.hairs.${h}`)}
                  selected={(look.hair ?? "short") === h}
                  onClick={() => set({ hair: h })}
                  preview={{ ...look, hair: h, extra: null }}
                />
              ))}
            </Tiles>
            {look.hair !== "wrap" && (
              <Dots
                legend={t("avatar.hairColor")}
                values={HAIR_COLORS}
                colors={HAIR_SWATCH}
                value={look.hair_color ?? "c1"}
                onChange={(hair_color) => set({ hair_color })}
              />
            )}
          </>
        )}
        {tab === "skin" && (
          <Tiles legend={t("avatar.skin")}>
            {SKINS.map((s, i) => (
              <Tile
                key={s}
                label={t("avatar.option", { legend: t("avatar.skin"), n: i + 1 })}
                selected={look.skin === s}
                onClick={() => set({ skin: s })}
                preview={{ ...look, skin: s }}
                swatch={SKIN_SWATCH[s]}
              />
            ))}
          </Tiles>
        )}
        {tab === "outfit" && (
          <Tiles legend={t("avatar.outfit")}>
            {OUTFITS.map((o, i) => (
              <Tile
                key={o}
                label={t("avatar.option", { legend: t("avatar.outfit"), n: i + 1 })}
                selected={look.outfit === o}
                onClick={() => set({ outfit: o })}
                preview={{ ...look, outfit: o }}
                swatch={OUTFIT_SWATCH[o]}
              />
            ))}
          </Tiles>
        )}
        {tab === "extras" && (
          <Tiles
            legend={t("avatar.extras")}
            aside={
              <span className="flex items-center gap-1 text-small text-ink/70">
                <Sprite name="star" scale={1} />
                {t("avatar.unlockMore")}
              </span>
            }
          >
            <Tile
              label={t("avatar.none")}
              selected={!look.extra}
              onClick={() => set({ extra: null })}
              preview={{ ...look, extra: null }}
            />
            {EXTRAS.map((x) => {
              const price = cosmetics[x] ?? 0;
              return (
                <Tile
                  key={x}
                  label={t(`avatar.items.${x}`)}
                  selected={look.extra === x}
                  locked={price > 0}
                  onClick={() => set({ extra: look.extra === x ? null : x })}
                  preview={{ ...look, extra: x }}
                  note={
                    price > 0 ? (
                      <span className="inline-flex items-center gap-1">
                        <Sprite name="lock" scale={1} alt={t("avatar.locked")} />
                        {t("avatar.points", { count: price })}
                      </span>
                    ) : undefined
                  }
                />
              );
            })}
          </Tiles>
        )}
      </div>

      <div className="mt-auto flex justify-between gap-3">
        <PixelButton variant="secondary" onClick={onBack}>
          {t("back")}
        </PixelButton>
        <PixelButton variant="spend" onClick={onNext}>
          {t("continue")}
        </PixelButton>
      </div>
    </PixelPanel>
  );
}

function Tiles({
  legend,
  aside,
  children,
}: {
  legend: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <fieldset className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <legend className="font-semibold">{legend}</legend>
        {aside}
      </div>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">{children}</div>
    </fieldset>
  );
}

function Tile({
  label,
  selected,
  locked,
  onClick,
  preview,
  swatch,
  note,
}: {
  label: string;
  selected: boolean;
  locked?: boolean;
  onClick: () => void;
  preview: AvatarLook;
  swatch?: string;
  note?: ReactNode;
}) {
  const calm = useCalmMotion();
  return (
    <motion.button
      type="button"
      disabled={locked}
      aria-pressed={selected}
      onClick={onClick}
      whileTap={calm || locked ? undefined : { scale: 0.92 }}
      className={cx(
        "relative flex flex-col items-center gap-1 rounded-pixel-step border-2 p-2 text-small",
        selected ? "border-primary bg-primary/10" : "border-sand bg-white hover:border-ink",
        locked && "cursor-not-allowed opacity-60 hover:border-sand",
      )}
    >
      <Avatar look={preview} size={56} />
      {swatch && (
        <span
          aria-hidden
          className="absolute end-1 top-1 h-4 w-4 rounded-full border-2 border-ink"
          // swatch colours are design tokens (tokens.json avatarSkin / brand colours)
          style={{ backgroundColor: swatch }}
        />
      )}
      <span className={cx("font-semibold", swatch && "sr-only")}>{label}</span>
      {note && <span className="text-ink/70">{note}</span>}
    </motion.button>
  );
}

function Dots({
  legend,
  values,
  colors,
  value,
  onChange,
}: {
  legend: string;
  values: readonly string[];
  colors: Record<string, string>;
  value: string;
  onChange: (v: string) => void;
}) {
  const { t } = useTranslation("onboarding");
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="font-semibold">{legend}</legend>
      <div className="flex flex-wrap gap-3">
        {values.map((v, i) => (
          <button
            key={v}
            type="button"
            aria-pressed={value === v}
            aria-label={t("avatar.option", { legend, n: i + 1 })}
            onClick={() => onChange(v)}
            className={cx(
              "h-11 w-11 rounded-full border-2 border-ink transition-transform",
              value === v && "scale-110 outline outline-2 outline-offset-2 outline-primary",
            )}
            // swatch colours are design tokens (tokens.json avatarHair)
            style={{ backgroundColor: colors[v] }}
          />
        ))}
      </div>
    </fieldset>
  );
}
