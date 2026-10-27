import { useMemo, type ReactNode } from "react";
import { I18nextProvider, useTranslation } from "react-i18next";
import { useUiStore } from "@/app/uiStore";
import {
  Banner,
  Bidi,
  Chip,
  CoinCounter,
  Input,
  LanguageSwitcher,
  LoadingStages,
  Mascot,
  MasteryRing,
  PixelButton,
  PixelPanel,
  PointsCounter,
  ProgressBar,
  RefillTimer,
  SegmentedProgress,
  SoftCard,
  Sprite,
  StreakCounter,
  WaterTile,
  type MascotPose,
  type SpriteName,
} from "@/components";
import { cx } from "@/components/cx";
import { dirFor, type Language } from "@/i18n/languages";
import { color } from "@/theme/tokens";
import { useSideBySide } from "./useSideBySide";

// Sample values for the dev route only — real screens read them from the API.
const SAMPLE = { coins: 20, points: 2340, streak: 6, refillSeconds: 6 * 3600 + 12 * 60 };

function Section({
  title,
  children,
  className,
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cx("min-w-0 rounded-soft border-2 border-sand bg-white p-4 sm:p-6", className)}
    >
      <h2 className="mb-4 text-h2">{title}</h2>
      {children}
    </section>
  );
}

function Label({ children }: { children: ReactNode }) {
  return (
    <p className="mb-2 text-small font-semibold uppercase tracking-wider text-ink/70">{children}</p>
  );
}

const SWATCHES = [
  { key: "whitewash", cls: "bg-whitewash", hex: color.whitewash },
  { key: "primary", cls: "bg-primary", hex: color.primary.DEFAULT },
  { key: "sea", cls: "bg-sea", hex: color.sea.DEFAULT },
  { key: "terracotta", cls: "bg-terracotta", hex: color.terracotta.DEFAULT },
  { key: "olive", cls: "bg-olive", hex: color.olive.DEFAULT },
  { key: "sand", cls: "bg-sand", hex: color.sand.DEFAULT },
  { key: "ink", cls: "bg-ink", hex: color.ink },
  { key: "danger", cls: "bg-danger", hex: color.danger.DEFAULT },
] as const;

const INK_SHADES = [
  { cls: "bg-sea-ink", hex: color.sea.ink },
  { cls: "bg-terracotta-ink", hex: color.terracotta.ink },
  { cls: "bg-olive-ink", hex: color.olive.ink },
] as const;

const ISLANDS = [
  { cls: "bg-island-1", course: "calculus" },
  { cls: "bg-island-2", course: "physics" },
  { cls: "bg-island-3", course: "dataStructures" },
  { cls: "bg-island-4", course: "english" },
  { cls: "bg-island-5", course: "chemistry" },
  { cls: "bg-island-6", course: "statistics" },
] as const;

function Colors() {
  const { t } = useTranslation("styleguide");
  return (
    <Section title={t("colors.title")} className="lg:col-span-2">
      <ul className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-8">
        {SWATCHES.map((s) => (
          <li key={s.key}>
            <div className={cx("h-20 rounded-pixel-step border-2 border-ink", s.cls)} />
            <p className="mt-2 font-semibold">{t(`colors.${s.key}`)}</p>
            <p className="text-small text-ink/70">
              <Bidi>{s.hex}</Bidi> · {t(`colors.${s.key}Use`)}
            </p>
          </li>
        ))}
      </ul>
      <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-3">
        <Label>{t("colors.inkShades")}</Label>
        {INK_SHADES.map((s) => (
          <span
            key={s.cls}
            className={cx("rounded-pixel-step px-3 py-1 font-semibold text-white", s.cls)}
          >
            Aa <Bidi>{s.hex}</Bidi>
          </span>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
        <Label>{t("colors.islandAccents")}</Label>
        {ISLANDS.map((i) => (
          <span key={i.cls} className="inline-flex items-center gap-2">
            <span aria-hidden className={cx("size-4", i.cls)} />
            {t(`colors.courses.${i.course}`)}
          </span>
        ))}
      </div>
      <p className="mt-4 text-small text-ink/70">{t("colors.note")}</p>
    </Section>
  );
}

function Type() {
  const { t } = useTranslation("styleguide");
  return (
    <Section title={t("type.title")}>
      <Label>{t("type.headingsLabel")}</Label>
      <p className="font-heading text-display">{t("type.display")}</p>
      <p className="font-heading text-h1">{t("type.h1")}</p>
      <p className="font-heading text-h2">{t("type.h2")}</p>
      <p className="font-heading text-h3">{t("type.h3")}</p>
      <div className="mt-4">
        <Label>{t("type.bodyLabel")}</Label>
        <p>
          {t("type.body")} <strong className="font-semibold">{t("type.bodyEmphasis")}</strong>
        </p>
        <p className="mt-2 text-small text-ink/70">{t("type.small")}</p>
      </div>
      <div lang="ar" dir="rtl" className="mt-4 rounded-soft bg-sand/40 p-4">
        <p className="font-heading text-h2">{t("type.bilingualTitle")}</p>
        <p>
          {t("type.bilingualLine")} <bdi lang="en">{t("type.bilingualLatin")}</bdi>
        </p>
      </div>
    </Section>
  );
}

function ButtonsAndInputs() {
  const { t } = useTranslation("styleguide");
  const { t: tc } = useTranslation();
  return (
    <Section title={t("buttons.title")}>
      <p className="mb-4 text-small text-ink/70">{t("buttons.note")}</p>
      <div className="flex flex-wrap gap-4 pb-1">
        <PixelButton variant="primary">{t("buttons.primary")}</PixelButton>
        <PixelButton variant="spend">{t("buttons.spend")}</PixelButton>
        <PixelButton variant="success">{t("buttons.success")}</PixelButton>
        <PixelButton variant="secondary">{t("buttons.secondary")}</PixelButton>
      </div>
      <div className="mt-4 flex flex-wrap gap-4 pb-1">
        <PixelButton pressed>{t("buttons.pressed")}</PixelButton>
        <PixelButton className="outline outline-2 outline-offset-2 outline-sea">
          {t("buttons.focus")}
        </PixelButton>
        <PixelButton disabled>{t("buttons.disabled")}</PixelButton>
      </div>
      <h3 className="mb-3 mt-8 text-h3">{t("inputs.title")}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <Input label={t("inputs.nickname")} defaultValue="SeaTurtle42" autoComplete="off" />
        <Input label={t("inputs.focused")} defaultValue="Engineering 2B" forceFocus />
        <Input label={t("inputs.inviteCode")} defaultValue="OLIVE-7Q2" code />
        <Input
          label={t("inputs.withError")}
          defaultValue="OLIV-72"
          error={tc("errors.code_not_found")}
        />
      </div>
    </Section>
  );
}

function CardsBannersChips() {
  const { t } = useTranslation("styleguide");
  const { t: tc } = useTranslation();
  return (
    <Section title={t("cards.title")}>
      <div className="grid gap-4 sm:grid-cols-2">
        <PixelPanel>
          <p className="font-semibold">{t("cards.pixelPanel")}</p>
          <p className="text-small text-ink/70">{t("cards.pixelPanelText")}</p>
        </PixelPanel>
        <SoftCard>
          <p className="font-semibold">{t("cards.softCard")}</p>
          <p className="text-small text-ink/70">{t("cards.softCardText")}</p>
        </SoftCard>
      </div>
      <div className="mt-4 flex flex-col gap-3">
        <Banner kind="queue">{tc("banner.queue", { seconds: 20 })}</Banner>
        <Banner kind="offline">{tc("banner.offline")}</Banner>
        <Banner kind="quickMode">{tc("banner.quickMode")}</Banner>
        <Banner kind="placement">{tc("banner.placement")}</Banner>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Chip kind="beginner">{tc("chip.beginner")}</Chip>
        <Chip kind="intermediate">{tc("chip.intermediate")}</Chip>
        <Chip kind="advanced">{tc("chip.advanced")}</Chip>
        <Chip kind="cost">{tc("chip.cost", { count: 5 })}</Chip>
        <Chip kind="quickMode">{tc("chip.quickMode")}</Chip>
        <Chip kind="weakSpot">{tc("chip.weakSpot")}</Chip>
        <Chip kind="confidence">{tc("chip.confidence", { level: tc("confidence.high") })}</Chip>
        <Chip kind="pinned">{tc("chip.pinned")}</Chip>
      </div>
    </Section>
  );
}

function CountersAndProgress() {
  const { t } = useTranslation("styleguide");
  return (
    <Section title={t("counters.title")}>
      <div className="flex flex-wrap gap-3">
        <CoinCounter value={SAMPLE.coins} />
        <PointsCounter value={SAMPLE.points} />
        <StreakCounter days={SAMPLE.streak} />
        <RefillTimer seconds={SAMPLE.refillSeconds} />
      </div>
      <dl className="mt-6 grid grid-cols-[auto_1fr] items-center gap-x-6 gap-y-4">
        <dt>{t("counters.bar")}</dt>
        <dd>
          <ProgressBar value={7} max={10} label={t("counters.bar")} />
        </dd>
        <dt>{t("counters.segmented")}</dt>
        <dd>
          <SegmentedProgress
            segments={[
              "correct",
              "correct",
              "wrong",
              "current",
              "pending",
              "pending",
              "pending",
              "pending",
            ]}
          />
        </dd>
        <dt>{t("counters.masteryRing")}</dt>
        <dd className="flex items-center gap-3">
          <MasteryRing value={0.7} accent={1} />
          <MasteryRing value={0.85} accent={3} />
          <MasteryRing value={0.4} accent={4} />
          <span className="text-small text-ink/70">{t("counters.masteryNote")}</span>
        </dd>
      </dl>
    </Section>
  );
}

function Loading() {
  const { t } = useTranslation("styleguide");
  const { t: tc } = useTranslation();
  return (
    <Section title={t("loading.title")}>
      <LoadingStages
        stages={[
          { key: "reading_chapter", state: "done" },
          { key: "matching_level", state: "done" },
          { key: "writing_questions", state: "inProgress" },
          { key: "writing_hints", state: "next" },
        ]}
        tip={tc("wisdom.sample")}
      />
    </Section>
  );
}

const PIECES: { name: SpriteName; key: string }[] = [
  { name: "tileBorder", key: "tileBorder" },
  { name: "blueDoor", key: "blueDoor" },
  { name: "bougainvillea", key: "bougainvillea" },
  { name: "oliveBranch", key: "oliveBranch" },
  { name: "jasmine", key: "jasmine" },
];
const ICONS: SpriteName[] = [
  "lantern",
  "lock",
  "trophy",
  "chest",
  "coin",
  "star",
  "flame",
  "hourglass",
];
const AVATARS: SpriteName[] = ["avatar1", "avatar2", "avatar3", "avatar4", "avatar5", "avatar6"];

function Tile({ children, caption }: { children: ReactNode; caption: string }) {
  return (
    <figure className="flex flex-col items-center justify-end gap-2 rounded-soft bg-sand/40 p-3 text-center">
      {children}
      <figcaption className="text-small font-semibold">{caption}</figcaption>
    </figure>
  );
}

function WorldPieces() {
  const { t } = useTranslation("styleguide");
  const { t: tc } = useTranslation();
  return (
    <Section title={t("world.title")} className="lg:col-span-2">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <WaterTile className="flex min-h-28 items-end justify-center rounded-soft p-2">
          <span className="rounded-pixel-step bg-ink px-2 py-1 text-small font-semibold text-white">
            {t("world.water")}
          </span>
        </WaterTile>
        {PIECES.map((p) => (
          <Tile key={p.name} caption={t(`world.${p.key}`)}>
            <Sprite name={p.name} scale={4} />
          </Tile>
        ))}
      </div>
      <div className="mt-6 flex flex-wrap items-center gap-3">
        {ICONS.map((name) => (
          <Sprite key={name} name={name} scale={2} alt={tc(`icons.${name}`)} />
        ))}
        <span className="text-small text-ink/70">{t("world.iconsLegend")}</span>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Label>{t("world.avatars")}</Label>
        {AVATARS.map((name, i) => (
          <Sprite key={name} name={name} scale={3} alt={t("world.avatar", { n: i + 1 })} />
        ))}
      </div>
    </Section>
  );
}

const BUILDINGS: { name: SpriteName; key: string }[] = [
  { name: "quizHall", key: "quiz" },
  { name: "tutorCafe", key: "tutor" },
  { name: "studyStudio", key: "studio" },
  { name: "audioStudio", key: "audio" },
  { name: "teachBackArena", key: "arena" },
];

function Buildings() {
  const { t } = useTranslation("styleguide");
  return (
    <Section title={t("buildings.title")} className="lg:col-span-2">
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {BUILDINGS.map((b) => (
          <li
            key={b.name}
            className="flex flex-col items-center gap-2 rounded-soft bg-sand/40 p-4 text-center"
          >
            <Sprite name={b.name} scale={3} />
            <p className="font-heading text-h3">{t(`buildings.${b.key}`)}</p>
            <p className="text-small text-ink/70">{t(`buildings.${b.key}Text`)}</p>
          </li>
        ))}
      </ul>
    </Section>
  );
}

const POSES: MascotPose[] = ["waving", "reading", "thinking", "celebrating"];

function MascotSection() {
  const { t } = useTranslation("styleguide");
  return (
    <Section title={t("mascot.title")} className="lg:col-span-2">
      <p className="mb-4 text-small text-ink/70">{t("mascot.note")}</p>
      <ul className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {POSES.map((pose) => (
          <li
            key={pose}
            className="flex flex-col items-center gap-2 rounded-soft bg-sand/40 p-4 text-center"
          >
            <Mascot pose={pose} scale={5} />
            <p className="font-heading text-h3">{t(`mascot.${pose}`)}</p>
            <p className="text-small text-ink/70">{t(`mascot.${pose}Use`)}</p>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-small text-ink/70">{t("placeholderNote")}</p>
    </Section>
  );
}

/** Everything below the header; rendered once, or twice (EN | AR) in side-by-side mode. */
function StyleguideContent({ compact }: { compact: boolean }) {
  return (
    // Compact: one column; override the sections' col-span-2, which would add an implicit track.
    <div className={cx("grid gap-6", compact ? "[&>*]:!col-span-1" : "lg:grid-cols-2")}>
      <Colors />
      <Type />
      <ButtonsAndInputs />
      <CardsBannersChips />
      <CountersAndProgress />
      <Loading />
      <WorldPieces />
      <Buildings />
      <MascotSection />
    </div>
  );
}

/** A column with its own language, `dir` and `lang`, independent of the page language. */
function LocalizedColumn({ lang }: { lang: Language }) {
  const { i18n } = useTranslation();
  const instance = useMemo(() => i18n.cloneInstance({ lng: lang }), [i18n, lang]);
  return (
    <I18nextProvider i18n={instance}>
      <div lang={lang} dir={dirFor(lang)} data-column={lang} className="min-w-0">
        <StyleguideContent compact />
      </div>
    </I18nextProvider>
  );
}

export function StyleguidePage() {
  const { t } = useTranslation("styleguide");
  const [sideBySide, setSideBySide] = useSideBySide();
  const reducedMotion = useUiStore((s) => s.reducedMotion);
  const setReducedMotion = useUiStore((s) => s.setReducedMotion);

  return (
    <main className="mx-auto max-w-screen-2xl px-4 py-8 sm:px-8">
      <header className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex items-center gap-4">
          <Sprite name="water" scale={4} />
          <div>
            <h1 className="text-h1">{t("title")}</h1>
            <p className="text-ink/70">{t("subtitle")}</p>
          </div>
        </div>
        <div className="flex flex-col gap-3">
          <LanguageSwitcher />
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            <label className="inline-flex min-h-11 items-center gap-2">
              <input
                type="checkbox"
                className="size-5 accent-primary"
                checked={sideBySide}
                onChange={(e) => setSideBySide(e.target.checked)}
              />
              {t("switcher.sideBySide")}
            </label>
            <label className="inline-flex min-h-11 items-center gap-2">
              <input
                type="checkbox"
                className="size-5 accent-primary"
                checked={reducedMotion}
                onChange={(e) => setReducedMotion(e.target.checked)}
              />
              {t("switcher.reducedMotion")}
            </label>
          </div>
        </div>
      </header>

      {sideBySide ? (
        <div className="grid gap-8 lg:grid-cols-2">
          <LocalizedColumn lang="en" />
          <LocalizedColumn lang="ar" />
        </div>
      ) : (
        <StyleguideContent compact={false} />
      )}
    </main>
  );
}
