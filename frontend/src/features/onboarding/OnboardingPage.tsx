import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, type ProfileIn, type StyleOut } from "@/api/client";
import { homePath } from "@/app/home";
import {
  type AvatarLook,
  Bidi,
  DEFAULT_LOOK,
  Input,
  LanguageSwitcher,
  Mascot,
  PixelButton,
  PixelPanel,
  Sprite,
} from "@/components";
import { cx } from "@/components/cx";
import { useMe } from "@/hooks/useSession";
import { AvatarBuilder } from "./AvatarBuilder";
import { ErrorBanner } from "@/features/worlds/parts";

const STEPS = ["profile", "style", "goals", "avatar", "languages"] as const;
type Step = (typeof STEPS)[number];
type Style = "visual" | "practice" | "listening" | "teaching";
const STYLES: Style[] = ["visual", "practice", "listening", "teaching"];
const QUESTIONS = ["formula", "exam", "lecture", "stuck"] as const;
const MINUTES = [15, 30, 45, 60, 90];
const LANGS = ["en", "fr", "ar", "ar-TN"] as const;
const BAR: Record<Style, string> = {
  visual: "bg-primary",
  practice: "bg-terracotta",
  listening: "bg-sea",
  teaching: "bg-olive",
};

/** /welcome — 5 short steps; "Skip for now" is always allowed (PRODUCT.md screens 3–4). */
export function OnboardingPage() {
  const { t } = useTranslation("onboarding");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const me = useMe().data;
  const [step, setStep] = useState<Step>("profile");
  const [profile, setProfile] = useState<{ university: string; field: string; year: string }>({
    university: "",
    field: "",
    year: "",
  });
  const [q, setQ] = useState(0);
  const [answers, setAnswers] = useState<(Style | null)[]>([null, null, null, null]);
  const [style, setStyle] = useState<StyleOut | null>(null);
  const [goal, setGoal] = useState<"pass" | "grade" | "deep" | null>(null);
  const [minutes, setMinutes] = useState<number | null>(null);
  const [reminder, setReminder] = useState("");
  const [look, setLook] = useState<AvatarLook>(DEFAULT_LOOK);
  const [langs, setLangs] = useState<string[]>([]);
  const [optIn, setOptIn] = useState(true);

  const n = STEPS.indexOf(step) + 1;

  const score = useMutation({
    mutationFn: () => api.scoreStyle(answers.filter(Boolean) as string[]),
    onSuccess: (s) => {
      setStyle(s);
      setStep("goals");
    },
  });

  const save = useMutation({
    mutationFn: (body: Partial<ProfileIn>) => api.saveProfile(body),
    onSuccess: async () => {
      const fresh = await api.me();
      qc.setQueryData(["me"], fresh);
      void navigate(await homePath(fresh), { replace: true });
    },
  });

  const skip = () => save.mutate({ finish: true });
  const finish = () =>
    save.mutate({
      university: profile.university.trim() || null,
      field: profile.field.trim() || null,
      year: profile.year ? Number(profile.year) : null,
      goal,
      daily_minutes: minutes,
      reminder_time: reminder || null,
      avatar: look,
      languages: langs as ProfileIn["languages"],
      leaderboard_opt_in: optIn,
      finish: true,
    });

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center gap-4 px-4 py-4 sm:px-8">
        <span className="flex items-center gap-2 font-heading text-h3">
          <Sprite name="island" scale={1} />
          {t("common:app.name")}
        </span>
        <div className="mx-auto flex w-full max-w-md flex-col gap-1 sm:w-auto sm:flex-1">
          <p className="text-small font-semibold">
            {t("progress", { n, total: STEPS.length, name: t(`steps.${step}`) })}
          </p>
          <ol className="flex gap-1" aria-hidden>
            {STEPS.map((s, i) => (
              <li
                key={s}
                className={cx(
                  "h-3 flex-1 rounded-pixel-step border-2 border-ink",
                  i < n ? "bg-primary" : "bg-sand",
                )}
              />
            ))}
          </ol>
        </div>
        <button
          type="button"
          onClick={skip}
          disabled={save.isPending}
          className="font-semibold text-primary underline"
        >
          {t("skip")}
        </button>
      </header>
      <ErrorBanner error={score.error ?? save.error} />

      <main className="mx-auto flex w-full max-w-screen-xl flex-1 flex-col gap-6 px-4 py-6 sm:px-8">
        {step === "profile" && (
          <PixelPanel className="mx-auto flex w-full max-w-xl flex-col gap-4">
            <h1 className="text-h2">{t("profile.title")}</h1>
            <p className="text-ink/70">{t("profile.body")}</p>
            <Input
              label={t("profile.university")}
              value={profile.university}
              maxLength={80}
              onChange={(e) => setProfile({ ...profile, university: e.target.value })}
            />
            <Input
              label={t("profile.field")}
              value={profile.field}
              maxLength={80}
              onChange={(e) => setProfile({ ...profile, field: e.target.value })}
            />
            <Input
              label={t("profile.year")}
              placeholder={t("profile.yearHint")}
              type="number"
              min={1}
              max={8}
              value={profile.year}
              onChange={(e) => setProfile({ ...profile, year: e.target.value })}
            />
            <Nav onNext={() => setStep("style")} />
          </PixelPanel>
        )}

        {step === "style" && (
          <section className="flex flex-col items-center gap-6 text-center">
            <p className="text-small font-semibold uppercase tracking-wider text-terracotta-ink">
              {t("style.question", { n: q + 1, total: QUESTIONS.length })}
            </p>
            <h1 className="max-w-3xl font-heading text-h1">{t(`style.${QUESTIONS[q]}.title`)}</h1>
            <p className="text-ink/70">{t("style.help")}</p>
            <div role="radiogroup" className="grid w-full gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {STYLES.map((s) => {
                const selected = answers[q] === s;
                return (
                  <button
                    key={s}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => setAnswers((a) => a.map((x, i) => (i === q ? s : x)))}
                    className={cx(
                      "relative flex flex-col gap-3 rounded-pixel-step border-2 bg-white p-4 text-start",
                      selected ? "border-primary bg-primary/5 shadow-panel" : "border-ink",
                    )}
                  >
                    {selected && (
                      <span className="absolute end-2 top-2 rounded-pixel-step bg-primary px-2 text-small text-white">
                        {t("style.selected")}
                      </span>
                    )}
                    <span className="flex h-24 items-center justify-center rounded-soft bg-sand/60">
                      <Sprite
                        name={
                          (
                            {
                              visual: "studyStudio",
                              practice: "quizHall",
                              listening: "audioStudio",
                              teaching: "teachBackArena",
                            } as const
                          )[s]
                        }
                        scale={2}
                      />
                    </span>
                    <span className="font-heading text-h3">
                      {t(`style.${QUESTIONS[q]}.${s}.title`)}
                    </span>
                    <span className="text-small text-ink/70">
                      {t(`style.${QUESTIONS[q]}.${s}.body`)}
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="flex gap-3">
              <PixelButton
                variant="secondary"
                onClick={() => (q > 0 ? setQ(q - 1) : setStep("profile"))}
              >
                {t("back")}
              </PixelButton>
              <PixelButton
                disabled={!answers[q] || score.isPending}
                onClick={() => (q + 1 < QUESTIONS.length ? setQ(q + 1) : score.mutate())}
              >
                {t("continue")}
              </PixelButton>
            </div>
          </section>
        )}

        {step === "goals" && (
          <PixelPanel className="mx-auto flex w-full max-w-xl flex-col gap-5">
            <h1 className="text-h2">{t("goals.title")}</h1>
            <Choice
              legend={t("goals.goal")}
              options={(["pass", "grade", "deep"] as const).map((g) => [g, t(`goals.${g}`)])}
              value={goal}
              onChange={setGoal}
            />
            <Choice
              legend={t("goals.minutes")}
              options={MINUTES.map((m) => [m, t("goals.minutesValue", { m })])}
              value={minutes}
              onChange={setMinutes}
            />
            <div className="flex flex-col gap-1">
              <label htmlFor="reminder" className="font-semibold">
                {t("goals.reminder")}
              </label>
              <input
                id="reminder"
                type="time"
                value={reminder}
                onChange={(e) => setReminder(e.target.value)}
                className="min-h-11 w-40 rounded-pixel-step border-2 border-ink bg-white px-3"
              />
            </div>
            <Nav onBack={() => setStep("style")} onNext={() => setStep("avatar")} />
          </PixelPanel>
        )}

        {step === "avatar" && (
          <div className="grid gap-6 lg:grid-cols-2">
            <StyleResult style={style} />
            <AvatarBuilder
              nickname={me?.nickname ?? ""}
              look={look}
              onChange={setLook}
              onNext={() => setStep("languages")}
              onBack={() => setStep("goals")}
            />
          </div>
        )}

        {step === "languages" && (
          <PixelPanel className="mx-auto flex w-full max-w-xl flex-col gap-5">
            <h1 className="text-h2">{t("languages.title")}</h1>
            <p className="text-ink/70">{t("languages.body")}</p>
            <fieldset className="flex flex-wrap gap-2">
              <legend className="mb-2 font-semibold">{t("languages.study")}</legend>
              {LANGS.map((l) => (
                <label
                  key={l}
                  lang={l}
                  className={cx(
                    "flex min-h-11 cursor-pointer items-center gap-2 rounded-pixel-step border-2 px-3 font-semibold",
                    langs.includes(l) ? "border-ink bg-primary text-white" : "border-sand bg-white",
                  )}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={langs.includes(l)}
                    onChange={() =>
                      setLangs((xs) => (xs.includes(l) ? xs.filter((x) => x !== l) : [...xs, l]))
                    }
                  />
                  {t(`common:language.${l}`)}
                </label>
              ))}
            </fieldset>
            <div className="flex flex-col gap-1">
              <p className="font-semibold">{t("languages.ui")}</p>
              <LanguageSwitcher />
            </div>
            <div className="flex items-start gap-3">
              <input
                id="leaderboard-opt-in"
                type="checkbox"
                checked={optIn}
                onChange={(e) => setOptIn(e.target.checked)}
                className="mt-1 h-5 w-5 accent-primary"
              />
              <label htmlFor="leaderboard-opt-in">
                <span className="font-semibold">{t("languages.leaderboard")}</span>
                <span className="block text-small text-ink/70">
                  {t("languages.leaderboardHelp")}
                </span>
              </label>
            </div>
            <div className="flex justify-between gap-3">
              <PixelButton variant="secondary" onClick={() => setStep("avatar")}>
                {t("back")}
              </PixelButton>
              <PixelButton variant="spend" onClick={finish} disabled={save.isPending}>
                {t("setSail")}
              </PixelButton>
            </div>
          </PixelPanel>
        )}
      </main>
    </div>
  );
}

function Nav({ onBack, onNext }: { onBack?: () => void; onNext: () => void }) {
  const { t } = useTranslation("onboarding");
  return (
    <div className="flex justify-between gap-3">
      {onBack ? (
        <PixelButton variant="secondary" onClick={onBack}>
          {t("back")}
        </PixelButton>
      ) : (
        <span />
      )}
      <PixelButton onClick={onNext}>{t("continue")}</PixelButton>
    </div>
  );
}

function Choice<V extends string | number>({
  legend,
  options,
  value,
  onChange,
}: {
  legend: string;
  options: [V, string][];
  value: V | null;
  onChange: (v: V) => void;
}) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 font-semibold">{legend}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map(([v, label]) => (
          <label
            key={String(v)}
            className={cx(
              "flex min-h-11 cursor-pointer items-center rounded-pixel-step border-2 px-3 font-semibold",
              value === v ? "border-ink bg-primary text-white" : "border-sand bg-white",
            )}
          >
            <input
              type="radio"
              className="sr-only"
              checked={value === v}
              onChange={() => onChange(v)}
            />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function StyleResult({ style }: { style: StyleOut | null }) {
  const { t } = useTranslation("onboarding");
  const { t: tc } = useTranslation();
  const mix = style?.mix ?? { visual: 25, practice: 25, listening: 25, teaching: 25 };
  const top = (style?.top ?? []) as Style[];
  return (
    <section className="flex flex-col gap-5 rounded-pixel-step bg-sand/50 p-6">
      <div className="flex items-center gap-4">
        <Mascot pose="celebrating" scale={3} />
        <div>
          <p className="text-small font-semibold uppercase tracking-wider text-terracotta-ink">
            {t("result.kicker")}
          </p>
          <h1 className="font-heading text-h1">
            {top.length === 2
              ? t("result.title", {
                  a: t(`result.styles.${top[0]}`),
                  b: t(`result.styles.${top[1]}`),
                })
              : t("result.titleSkipped")}
          </h1>
        </div>
      </div>
      <PixelPanel className="flex flex-col gap-3">
        {STYLES.map((s) => (
          <div key={s} className="grid grid-cols-[6rem_1fr_3rem] items-center gap-3">
            <span className="font-semibold">{t(`result.labels.${s}`)}</span>
            <div
              role="progressbar"
              aria-label={t(`result.labels.${s}`)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={mix[s] ?? 0}
              className="h-4 overflow-hidden rounded-pixel-step border-2 border-ink bg-sand"
            >
              <div className={cx("h-full", BAR[s])} style={{ inlineSize: `${mix[s] ?? 0}%` }} />
            </div>
            <Bidi className="text-end font-semibold">{`${mix[s] ?? 0}%`}</Bidi>
          </div>
        ))}
      </PixelPanel>
      {style && (
        <p>
          {t("result.suggest", {
            a: tc(`buildings.${style.suggested_buildings[0]}`),
            b: tc(`buildings.${style.suggested_buildings[1]}`),
          })}
        </p>
      )}
    </section>
  );
}
