import { useId, type InputHTMLAttributes } from "react";
import { cx } from "./cx";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  /** Already-translated error message; marks the field invalid. */
  error?: string;
  /** Join codes: wide tracking, uppercase. */
  code?: boolean;
  /** Force the focused look (styleguide only). */
  forceFocus?: boolean;
}

export function Input({ label, error, code, forceFocus, className, id, ...rest }: InputProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const errorId = `${inputId}-error`;
  return (
    <div className={cx("flex flex-col gap-1", className)}>
      <label htmlFor={inputId} className="font-semibold">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        className={cx(
          "min-h-11 rounded-pixel-step border-2 bg-white px-3 py-2 text-ink",
          "focus:border-sea-ink focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-sea",
          error ? "border-danger" : "border-ink",
          forceFocus && "border-sea-ink outline outline-2 outline-offset-1 outline-sea",
          code && "font-semibold uppercase tracking-[0.2em]",
        )}
        {...rest}
      />
      {error && (
        <p id={errorId} className="text-small text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
