import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, type WorldOut } from "@/api/client";
import { Input, LanguageSwitcher, PixelButton, PixelPanel, Sprite } from "@/components";
import { cx } from "@/components/cx";
import { ErrorBanner, JoinCard, WorldSummaryBar } from "./parts";
import { UploadStep } from "./UploadStep";

const STEPS = ["name", "courses", "chapters", "upload"] as const;
type Step = (typeof STEPS)[number];

interface DraftCourse {
  key: number;
  name: string;
  chapters: string[];
}

let nextKey = 1;
const blankCourse = (): DraftCourse => ({ key: nextKey++, name: "", chapters: [""] });

/** /worlds/new — mockup 04: join by code, or the 4-step create wizard ending in uploads. */
export function CreateOrJoinPage() {
  const { t } = useTranslation("worlds");
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("name");
  const [name, setName] = useState("");
  const [courses, setCourses] = useState<DraftCourse[]>([blankCourse()]);
  const [world, setWorld] = useState<WorldOut | null>(null);
  const [touched, setTouched] = useState(false);

  const n = STEPS.indexOf(step) + 1;
  const named = courses.filter((c) => c.name.trim());
  const chaptersOk = named.every((c) => c.chapters.some((ch) => ch.trim()));

  // The world is created only once its courses and chapters are known (no half-built worlds).
  const build = useMutation({
    mutationFn: async () => {
      const created = await api.createWorld(name.trim());
      for (const c of named) {
        await api.addCourse(
          created.id,
          c.name.trim(),
          c.chapters.filter((ch) => ch.trim()),
        );
      }
      return api.world(created.id);
    },
    onSuccess: (w) => {
      setWorld(w);
      setStep("upload");
    },
  });

  const next = () => {
    setTouched(true);
    if (step === "name" && name.trim()) return goto("courses");
    if (step === "courses" && named.length) return goto("chapters");
    if (step === "chapters" && chaptersOk) build.mutate();
  };
  const goto = (s: Step) => {
    setTouched(false);
    setStep(s);
  };
  const back = () => {
    if (step === "courses") goto("name");
    else if (step === "chapters") goto("courses");
  };
  const update = (key: number, change: Partial<DraftCourse>) =>
    setCourses((cs) => cs.map((c) => (c.key === key ? { ...c, ...change } : c)));

  return (
    <main className="mx-auto flex max-w-screen-xl flex-col gap-6 px-4 py-6 sm:px-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <span className="flex items-center gap-2 font-heading text-h3">
          <Sprite name="oliveBranch" scale={2} />
          {t("common:app.name")}
        </span>
        <LanguageSwitcher />
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <section className="flex min-w-0 flex-col gap-5">
          <div>
            <h1 className="text-h1">{t("title")}</h1>
            <p className="mt-2 text-ink/70">{t("intro")}</p>
          </div>
          <JoinCard />
          <div className="rounded-pixel-step border-2 border-primary bg-primary/5 p-4">
            <h2 className="text-h3">{t("create.title")}</h2>
            <p className="text-small text-ink/70">{t("create.subtitle")}</p>
            <p className="mt-2 text-small font-semibold text-primary">
              {t("create.progress", { n, total: STEPS.length })}
            </p>
          </div>
        </section>

        <PixelPanel className="flex min-w-0 flex-col gap-5">
          <ol aria-label={t("steps.label")} className="flex flex-wrap gap-x-5 gap-y-2">
            {STEPS.map((s, i) => {
              const done = i + 1 < n;
              const current = s === step;
              return (
                <li
                  key={s}
                  aria-current={current ? "step" : undefined}
                  className="flex items-center gap-2 font-semibold"
                >
                  <span
                    aria-hidden
                    className={cx(
                      "inline-flex h-7 w-7 items-center justify-center rounded-pixel-step text-small text-white",
                      done ? "bg-olive-ink" : current ? "bg-primary" : "bg-sand-dark",
                    )}
                  >
                    {done ? "✓" : i + 1}
                  </span>
                  <span className={current || done ? "" : "text-ink/60"}>{t(`steps.${s}`)}</span>
                </li>
              );
            })}
          </ol>
          <p className="sr-only" aria-live="polite">
            {t("steps.current", { n, total: STEPS.length, name: t(`steps.${step}`) })}
          </p>

          {step === "name" && (
            <Input
              label={t("name.label")}
              placeholder={t("name.placeholder")}
              value={name}
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && next()}
              error={touched && !name.trim() ? t("name.help") : undefined}
            />
          )}

          {step === "courses" && (
            <fieldset className="flex flex-col gap-3">
              <legend className="mb-1 text-h3">{t("courses.heading")}</legend>
              <p className="text-small text-ink/70">{t("courses.help")}</p>
              {courses.map((c, i) => (
                <div key={c.key} className="flex items-end gap-2">
                  <Input
                    className="min-w-0 flex-1"
                    label={t("courses.label")}
                    placeholder={t("courses.placeholder")}
                    value={c.name}
                    maxLength={80}
                    onChange={(e) => update(c.key, { name: e.target.value })}
                  />
                  {courses.length > 1 && (
                    <PixelButton
                      variant="secondary"
                      aria-label={t("courses.remove", { name: c.name || i + 1 })}
                      onClick={() => setCourses((cs) => cs.filter((x) => x.key !== c.key))}
                    >
                      ×
                    </PixelButton>
                  )}
                </div>
              ))}
              {touched && !named.length && (
                <p className="text-small text-danger">{t("courses.needOne")}</p>
              )}
              <PixelButton
                variant="secondary"
                className="self-start"
                onClick={() => setCourses((cs) => [...cs, blankCourse()])}
              >
                {t("courses.add")}
              </PixelButton>
            </fieldset>
          )}

          {step === "chapters" && (
            <div className="flex flex-col gap-5">
              {named.map((c) => (
                <fieldset key={c.key} className="flex flex-col gap-2">
                  <legend className="mb-1 text-h3">
                    {t("chapters.heading", { course: c.name.trim() })}
                  </legend>
                  {c.chapters.map((ch, i) => (
                    <div key={i} className="flex items-end gap-2">
                      <span className="mb-3 w-6 text-end font-semibold text-ink/60">{i + 1}</span>
                      <Input
                        className="min-w-0 flex-1"
                        label={t("chapters.label")}
                        placeholder={t("chapters.placeholder")}
                        value={ch}
                        maxLength={120}
                        onChange={(e) =>
                          update(c.key, {
                            chapters: c.chapters.map((x, j) => (j === i ? e.target.value : x)),
                          })
                        }
                      />
                      {c.chapters.length > 1 && (
                        <PixelButton
                          variant="secondary"
                          aria-label={t("chapters.remove", { title: ch || i + 1 })}
                          onClick={() =>
                            update(c.key, { chapters: c.chapters.filter((_, j) => j !== i) })
                          }
                        >
                          ×
                        </PixelButton>
                      )}
                    </div>
                  ))}
                  {touched && !c.chapters.some((x) => x.trim()) && (
                    <p className="text-small text-danger">{t("chapters.needOne")}</p>
                  )}
                  <PixelButton
                    variant="secondary"
                    className="self-start"
                    onClick={() => update(c.key, { chapters: [...c.chapters, ""] })}
                  >
                    {t("chapters.add")}
                  </PixelButton>
                </fieldset>
              ))}
              <ErrorBanner error={build.error} />
            </div>
          )}

          {step === "upload" && world && (
            <>
              <WorldSummaryBar name={world.name} courses={world.courses} />
              <UploadStep
                world={world}
                onBuild={() => void navigate(`/worlds/${world.id}/indexing`)}
              />
            </>
          )}

          {step !== "upload" && (
            <div className="flex flex-wrap justify-end gap-3">
              {step !== "name" && (
                <PixelButton variant="secondary" onClick={back}>
                  {t("nav.back")}
                </PixelButton>
              )}
              <PixelButton onClick={next} disabled={build.isPending}>
                {t("nav.next")}
              </PixelButton>
            </div>
          )}
        </PixelPanel>
      </div>
    </main>
  );
}
