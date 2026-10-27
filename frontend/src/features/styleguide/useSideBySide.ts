import { useSearchParams } from "react-router-dom";

/** `?compare=1` so a side-by-side view can be linked and screenshotted directly. */
export function useSideBySide(): [boolean, (on: boolean) => void] {
  const [params, setParams] = useSearchParams();
  const on = params.get("compare") === "1";
  const set = (value: boolean) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set("compare", "1");
        else next.delete("compare");
        return next;
      },
      { replace: true },
    );
  return [on, set];
}
