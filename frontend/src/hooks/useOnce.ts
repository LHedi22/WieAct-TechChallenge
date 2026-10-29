import { useEffect, useRef } from "react";

/** Run `fn` once per mount, even under StrictMode's double effects in dev: actions that create
 * something (a session, a quiz attempt, a job) must not be sent twice. */
export function useOnce(fn: () => void) {
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    fn();
  }, [fn]);
}
