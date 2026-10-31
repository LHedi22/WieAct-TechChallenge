import { useReducedMotion } from "framer-motion";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { MapCourse } from "@/api/client";
import { useUiStore } from "@/app/uiStore";
import { Bidi, MasteryRing, PixelButton, Sprite, WaterTile } from "@/components";
import { cx } from "@/components/cx";
import { BOAT, type Slot, accentOf, slotsFor } from "./layout";

export type Zoom = 1 | 2 | 3;

interface Props {
  courses: MapCourse[];
  zoom?: Zoom;
  /** Open an island (after the boat sails there). */
  onOpen?: (course: MapCourse) => void;
  /** Locked island: start its placement quiz. */
  onPlacement?: (course: MapCourse) => void;
  /** Landing preview: no buttons, no boat trips. */
  preview?: boolean;
  className?: string;
}

const SAIL_MS = 500; // cosmetic, ≤ 600 ms (DESIGN.md mockup fix 9)

/** The archipelago. Geography is not mirrored in RTL (the scene is dir="ltr"), but every label
 * keeps the reader's direction. Positions come from design/assets/layout.json. */
export function MapScene({ courses, zoom = 1, onOpen, onPlacement, preview, className }: Props) {
  const { t, i18n } = useTranslation("map");
  const systemReduced = useReducedMotion();
  const appReduced = useUiStore((s) => s.reducedMotion);
  const reduced = Boolean(systemReduced) || appReduced;
  const [boat, setBoat] = useState(BOAT);
  const slots = slotsFor(courses.length);
  const dir = i18n.dir();
  // bigger slots (fewer courses) get bigger islands; always an integer scale
  const scaleFor = (slot: Slot) =>
    (preview ? 2 : Math.min(6, (slot.w >= 26 ? 4 : slot.w >= 20 ? 3 : 2) + zoom)) as
      2 | 3 | 4 | 5 | 6;

  const sail = (course: MapCourse, i: number) => {
    const slot = slots[i % slots.length]!;
    if (reduced || !onOpen) return onOpen?.(course);
    setBoat({ x: slot.x, y: slot.y + (slot.label === "below" ? -10 : 10) });
    window.setTimeout(() => onOpen(course), SAIL_MS);
  };

  return (
    <div className={cx("overflow-auto rounded-pixel-step", className)}>
      <WaterTile className="relative min-h-full">
        <div
          dir="ltr"
          className="relative"
          // the landing preview fits its box; the real map scrolls when zoomed or on small screens
          style={
            preview
              ? { aspectRatio: "16 / 10" }
              : { minWidth: `${640 + zoom * 320}px`, minHeight: "100%", aspectRatio: "16 / 10" }
          }
          data-testid="map-scene"
        >
          {courses.slice(0, slots.length).map((course, i) => {
            const slot = slots[i]!;
            const locked = !preview && course.ready && course.level === null;
            const risen = preview || course.ready;
            const label = (
              <div
                dir={dir}
                className="pointer-events-auto flex min-w-36 max-w-56 flex-col gap-1 rounded-pixel-step border-2 border-ink bg-white px-3 py-2 shadow-panel"
              >
                <div className="flex items-center gap-2">
                  {risen && !locked && course.level !== null && (
                    <MasteryRing
                      value={course.mastery / 100}
                      accent={accentOf(course.color_key)}
                      size={28}
                    />
                  )}
                  {locked && <Sprite name="lock" scale={1} />}
                  <Bidi className="font-semibold leading-tight">{course.name}</Bidi>
                </div>
                {!preview && (
                  <p className="text-small text-ink/70">
                    {!course.ready
                      ? t("island.rising")
                      : locked
                        ? t("island.waitingPlacement")
                        : t("island.mastery", { percent: course.mastery })}
                  </p>
                )}
                {locked && onPlacement && (
                  <PixelButton
                    variant="spend"
                    className="mt-1 text-small"
                    onClick={() => onPlacement(course)}
                  >
                    {t("island.startPlacement")}
                  </PixelButton>
                )}
              </div>
            );
            return (
              <div
                key={course.id}
                className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-2"
                // physical position on purpose: the map is geography, never mirrored
                style={{ left: `${slot.x}%`, top: `${slot.y}%` }}
                data-island={course.id}
                data-state={!risen ? "sea" : locked ? "locked" : "open"}
              >
                {slot.label === "above" && label}
                {risen ? (
                  preview || !onOpen ? (
                    <Sprite
                      name="island"
                      scale={scaleFor(slot)}
                      className={cx(i % 2 === 1 && "-scale-x-100")}
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => (locked ? onPlacement?.(course) : sail(course, i))}
                      aria-label={
                        locked
                          ? t("island.startPlacementFor", { name: course.name })
                          : t("island.open", { name: course.name })
                      }
                      className="rounded-pixel-step focus-visible:outline focus-visible:outline-4 focus-visible:outline-sea"
                    >
                      <Sprite
                        name={locked ? "islandLocked" : "island"}
                        scale={scaleFor(slot)}
                        // every other island is flipped so neighbours don't look alike
                        className={cx(
                          i % 2 === 1 && "-scale-x-100",
                          locked && "opacity-90 grayscale-[0.7]",
                        )}
                      />
                    </button>
                  )
                ) : (
                  <div
                    style={{ width: 48 * scaleFor(slot), height: 32 * scaleFor(slot) }}
                    aria-hidden
                  />
                )}
                {slot.label === "below" && label}
              </div>
            );
          })}
          {!preview && (
            <div
              className="absolute -translate-x-1/2 -translate-y-1/2 transition-[left,top] ease-in-out"
              style={{
                left: `${boat.x}%`,
                top: `${boat.y}%`,
                transitionDuration: reduced ? "0ms" : `${SAIL_MS}ms`,
              }}
              aria-hidden
            >
              <Sprite name="boat" scale={3} />
            </div>
          )}
        </div>
      </WaterTile>
    </div>
  );
}
