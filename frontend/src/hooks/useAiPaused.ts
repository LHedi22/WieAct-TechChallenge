import { useSystemStatus } from "./useSystemStatus";

/** Offline demo mode: new AI actions are paused (outside our slot); saved results still open. */
export function useAiPaused(): boolean {
  return useSystemStatus().data?.offline_demo_mode ?? false;
}
