import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import type { MapCourse } from "@/api/client";
import { homePath } from "@/app/home";
import { LanguageSwitcher, PixelButton, Sprite, type SpriteName } from "@/components";
import { useMe } from "@/hooks/useSession";
import { MapScene } from "@/features/map/MapScene";

const BUILDINGS: [string, SpriteName][] = [
  ["quiz_hall", "quizHall"],
  ["socratic_tutor", "tutorCafe"],
  ["study_studio", "studyStudio"],
  ["audio_studio", "audioStudio"],
  ["teachback_arena", "teachBackArena"],
];

/** / — the promise, a sample archipelago, Start, the language picker (mockup 01). */
export function LandingPage() {
  const { t } = useTranslation("landing");
  const { t: tc } = useTranslation();
  const navigate = useNavigate();
  const me = useMe().data;

  const sample: MapCourse[] = (["calculus", "dataStructures", "english"] as const).map((k, i) => ({
    id: k,
    name: t(`sample.${k}`),
    color_key: `island-${i + 1}`,
    ready: true,
    chapters: 3,
    level: "intermediate",
    mastery: 0,
  }));

  const start = async () => {
    if (!me) return void navigate("/signup");
    void navigate(await homePath(me));
  };

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-8">
        <span className="flex items-center gap-2 font-heading text-h3">
          <Sprite name="island" scale={1} />
          {tc("app.name")}
        </span>
        <LanguageSwitcher />
      </header>
      <main className="mx-auto grid w-full max-w-screen-xl flex-1 items-center gap-8 px-4 py-6 sm:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <section className="flex min-w-0 flex-col gap-5">
          <Sprite name="oliveBranch" scale={3} />
          <h1 className="font-heading text-[2.5rem] leading-tight sm:text-display">{t("title")}</h1>
          <p className="max-w-prose text-ink/80">{t("body")}</p>
          <div className="flex flex-wrap items-center gap-4">
            <PixelButton variant="spend" onClick={() => void start()}>
              {me ? t("continue") : t("start")}{" "}
              <span aria-hidden className="rtl:rotate-180 inline-block">
                →
              </span>
            </PixelButton>
            <span className="text-small text-ink/70">{t("free")}</span>
          </div>
          {!me && (
            <p className="text-small">
              {t("haveAccount")}{" "}
              <Link to="/signin" className="font-semibold text-primary underline">
                {t("signIn")}
              </Link>
            </p>
          )}
        </section>
        <MapScene courses={sample} preview className="min-w-0 border-2 border-ink" />
      </main>
      <ul
        className="flex flex-wrap justify-center gap-x-8 gap-y-3 px-4 py-6"
        aria-label={t("buildings")}
      >
        {BUILDINGS.map(([key, sprite]) => (
          <li key={key} className="flex items-center gap-2 text-small">
            <Sprite name={sprite} scale={1} />
            {tc(`buildings.${key}`)}
          </li>
        ))}
      </ul>
    </div>
  );
}
