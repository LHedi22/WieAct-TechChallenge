import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { AudioEpisode } from "@/api/client";
import { PixelButton, PixelPanel, SoftCard } from "@/components";
import { cx } from "@/components/cx";

type Script = NonNullable<AudioEpisode["script"]>;

const RATES = [0.75, 1, 1.25, 1.5];
// The browser voice to look for per UI language. Darija has none: transcript only (DECISIONS).
const VOICE_PREFIX: Record<string, string | null> = { en: "en", fr: "fr", ar: "ar", "ar-TN": null };

function speech(): SpeechSynthesis | null {
  return typeof window !== "undefined" && "speechSynthesis" in window
    ? window.speechSynthesis
    : null;
}

/** The browser's voice for this language, if any (voices can arrive after the first render). */
function useVoice(language: string) {
  const synth = speech();
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(() => synth?.getVoices() ?? []);
  useEffect(() => {
    if (!synth) return;
    const update = () => setVoices(synth.getVoices());
    synth.addEventListener("voiceschanged", update);
    return () => synth.removeEventListener("voiceschanged", update);
  }, [synth]);
  const prefix = VOICE_PREFIX[language] ?? null;
  const voice = prefix ? voices.find((v) => v.lang.toLowerCase().startsWith(prefix)) : undefined;
  return { synth, voice, darija: language === "ar-TN" };
}

/** Transcript with the current segment highlighted, play/pause and speed. Segments are spoken one
 * by one so the highlight follows; pausing stops after the current one is cancelled and resuming
 * restarts that segment (pause/resume is unreliable across browsers). */
export function Player({ script, language }: { script: Script; language: string }) {
  const { t } = useTranslation("audio");
  const { synth, voice, darija } = useVoice(language);
  const [current, setCurrent] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const run = useRef(0); // bumped on every stop/restart: stale `onend`s are ignored
  const rateId = useId();
  const canSpeak = !!synth && !!voice;

  const speakFrom = useCallback(
    (i: number, r: number) => {
      if (!synth || !voice) return;
      const id = ++run.current;
      synth.cancel();
      const say = (k: number) => {
        if (k >= script.segments.length) {
          setPlaying(false);
          setCurrent(0);
          return;
        }
        setCurrent(k);
        const u = new SpeechSynthesisUtterance(script.segments[k]);
        u.voice = voice;
        u.lang = voice.lang;
        u.rate = r;
        u.onend = () => {
          if (run.current === id) say(k + 1);
        };
        synth.speak(u);
      };
      setPlaying(true);
      say(i);
    },
    [synth, voice, script.segments],
  );
  const stop = useCallback(() => {
    run.current++;
    synth?.cancel();
    setPlaying(false);
  }, [synth]);

  useEffect(() => stop, [stop]); // leaving the page stops the voice

  return (
    <section className="flex flex-col gap-4" data-testid="audio-player">
      <h2 className="text-h2" dir="auto">
        {script.title || t("title")}
      </h2>
      {!canSpeak && (
        <SoftCard className="bg-sand/20" data-testid="transcript-only">
          {darija ? t("darija") : t("noVoice")}
        </SoftCard>
      )}
      {canSpeak && (
        <PixelPanel className="flex flex-wrap items-center gap-4">
          <PixelButton
            onClick={() => (playing ? stop() : speakFrom(current, rate))}
            aria-pressed={playing}
          >
            {playing ? t("pause") : t("play")}
          </PixelButton>
          <div className="flex items-center gap-2">
            <label htmlFor={rateId} className="font-semibold">
              {t("speed")}
            </label>
            <select
              id={rateId}
              value={rate}
              onChange={(e) => {
                const r = Number(e.target.value);
                setRate(r);
                if (playing) speakFrom(current, r);
              }}
              className="min-h-11 rounded-pixel-step border-2 border-ink bg-white px-3"
            >
              {RATES.map((r) => (
                <option key={r} value={r}>
                  {r}×
                </option>
              ))}
            </select>
          </div>
          <p className="text-small text-ink/70">
            {t("segment", { n: current + 1, total: script.segments.length })}
          </p>
        </PixelPanel>
      )}
      <ol className="flex flex-col gap-2" aria-label={t("transcript")}>
        {script.segments.map((s, i) => (
          <li key={i}>
            <button
              type="button"
              disabled={!canSpeak}
              aria-current={playing && i === current ? "true" : undefined}
              onClick={() => speakFrom(i, rate)}
              className={cx(
                "w-full rounded-soft border-2 p-3 text-start disabled:cursor-default",
                playing && i === current
                  ? "border-primary bg-primary/10 font-semibold"
                  : "border-sand bg-white",
              )}
              dir="auto"
            >
              {s}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
