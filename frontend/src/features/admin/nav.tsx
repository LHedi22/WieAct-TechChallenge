// The admin side nav: only finished pages are listed.
import type { ReactNode } from "react";
import { StatsPage } from "./StatsPage";
import { SwitchesPage } from "./SwitchesPage";

export interface NavItem {
  path: string;
  label: string;
  element: ReactNode;
}

export const HOME = "switches";

export const NAV: NavItem[] = [
  { path: "switches", label: "Switches", element: <SwitchesPage /> },
  { path: "stats", label: "Stats", element: <StatsPage /> },
];
