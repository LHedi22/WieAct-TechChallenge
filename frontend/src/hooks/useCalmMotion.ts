import { useReducedMotion } from "framer-motion";
import { useUiStore } from "@/app/uiStore";

/** True when motion should stay still: the OS setting or the in-app reduced-motion switch. */
export function useCalmMotion(): boolean {
  const system = useReducedMotion();
  const app = useUiStore((s) => s.reducedMotion);
  return Boolean(system) || app;
}
