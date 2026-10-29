import layout from "../../../../design/assets/layout.json";
import type { IslandAccent } from "@/components";

export interface Slot {
  x: number;
  y: number;
  w: number;
  label: "below" | "above";
}

const ISLANDS = layout.islands as Record<string, Slot[]>;
export const MAX_ISLANDS = 8;

/** Island slots for a world with n courses (positions from design/assets/layout.json). Worlds with
 * more than 8 courses reuse the 8-slot layout; the list view always shows every course. */
export function slotsFor(n: number): Slot[] {
  const k = Math.min(Math.max(n, 1), MAX_ISLANDS);
  return ISLANDS[String(k)] ?? ISLANDS["1"]!;
}

export const BUILDING_POSITIONS = layout.buildings as Record<string, { x: number; y: number }>;
export const BOAT = layout.boat;
export const EXPLORER = layout.explorer;

/** "island-3" → 3 (the course's accent among the 6 island tokens). */
export function accentOf(colorKey: string): IslandAccent {
  const n = Number(colorKey.replace("island-", ""));
  return (n >= 1 && n <= 6 ? n : 1) as IslandAccent;
}
