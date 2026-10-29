import { color } from "@/theme/tokens";

export interface AvatarLook {
  skin: string; // s1…s5
  outfit: string; // o1…o5
  extra?: string | null; // cap | glasses | scarf | chechia | headphones
}

export const SKINS = ["s1", "s2", "s3", "s4", "s5"] as const;
export const OUTFITS = ["o1", "o2", "o3", "o4", "o5"] as const;
export const EXTRAS = ["cap", "glasses", "scarf", "chechia", "headphones"] as const;

export const SKIN_SWATCH: Record<string, string> = Object.fromEntries(
  SKINS.map((k, i) => [k, color.avatarSkin[i] ?? color.avatarSkin[0]!]),
);
export const OUTFIT_SWATCH: Record<string, string> = {
  o1: color.sea.DEFAULT,
  o2: color.primary.DEFAULT,
  o3: color.terracotta.DEFAULT,
  o4: color.olive.DEFAULT,
  o5: color.sand.DEFAULT,
};

export const DEFAULT_LOOK: AvatarLook = { skin: "s2", outfit: "o1", extra: "cap" };
