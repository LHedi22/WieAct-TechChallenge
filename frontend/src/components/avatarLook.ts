import { color } from "@/theme/tokens";

export interface AvatarLook {
  skin: string; // s1…s5
  outfit: string; // o1…o5
  hair?: string | null; // short | curly | long | bun | spiky | wrap (older looks: none → short)
  hair_color?: string | null; // c1…c4
  extra?: string | null; // cap | glasses | scarf | chechia | headphones
}

export const SKINS = ["s1", "s2", "s3", "s4", "s5"] as const;
export const OUTFITS = ["o1", "o2", "o3", "o4", "o5"] as const;
export const HAIRS = ["short", "curly", "long", "bun", "spiky", "wrap"] as const;
export const HAIR_COLORS = ["c1", "c2", "c3", "c4"] as const;
export const EXTRAS = ["cap", "glasses", "scarf", "chechia", "headphones"] as const;

export const SKIN_SWATCH: Record<string, string> = Object.fromEntries(
  SKINS.map((k, i) => [k, color.avatarSkin[i] ?? color.avatarSkin[0]!]),
);
export const HAIR_SWATCH: Record<string, string> = Object.fromEntries(
  HAIR_COLORS.map((k, i) => [k, color.avatarHair[i] ?? color.avatarHair[0]!]),
);
export const OUTFIT_SWATCH: Record<string, string> = {
  o1: color.sea.DEFAULT,
  o2: color.primary.DEFAULT,
  o3: color.terracotta.DEFAULT,
  o4: color.olive.DEFAULT,
  o5: color.bougainvillea,
};

export const DEFAULT_LOOK: AvatarLook = {
  skin: "s2",
  outfit: "o1",
  hair: "short",
  hair_color: "c1",
  extra: null,
};
