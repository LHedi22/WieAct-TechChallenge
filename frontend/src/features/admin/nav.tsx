// The admin side nav: only finished pages are listed.
import type { ReactNode } from "react";
import {
  ArenaPage,
  CacheList,
  ContentPage,
  JobsList,
  LogPage,
  UsersPage,
  WorldsPage,
} from "./pages";
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
  { path: "users", label: "Users", element: <UsersPage /> },
  { path: "worlds", label: "Worlds", element: <WorldsPage /> },
  { path: "content", label: "Content", element: <ContentPage /> },
  { path: "arena", label: "Arena", element: <ArenaPage /> },
  { path: "jobs", label: "Jobs", element: <JobsList /> },
  { path: "cache", label: "Cache", element: <CacheList /> },
  { path: "log", label: "Admin log", element: <LogPage /> },
];
