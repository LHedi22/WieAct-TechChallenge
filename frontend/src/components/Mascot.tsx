import { useTranslation } from "react-i18next";
import { Sprite, type SpriteScale } from "./sprite/Sprite";
import type { SpriteName } from "./sprite/registry";

export type MascotPose = "waving" | "reading" | "thinking" | "celebrating";

const SPRITE: Record<MascotPose, SpriteName> = {
  waving: "catWaving",
  reading: "catReading",
  thinking: "catThinking",
  celebrating: "catCelebrating",
};

/** The Sidi Bou Said cat. Loading, empty states, tips, onboarding result — never in study screens. */
export function Mascot({ pose, scale = 4 }: { pose: MascotPose; scale?: SpriteScale }) {
  const { t } = useTranslation();
  return <Sprite name={SPRITE[pose]} scale={scale} alt={t(`mascot.${pose}`)} />;
}
