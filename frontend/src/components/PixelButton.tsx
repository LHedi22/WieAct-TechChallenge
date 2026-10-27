import type { ButtonHTMLAttributes } from "react";
import { cx } from "./cx";

export type PixelButtonVariant = "primary" | "spend" | "success" | "secondary";

interface PixelButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: PixelButtonVariant;
  /** Force the pressed look (styleguide); real presses use :active. */
  pressed?: boolean;
}

// *-ink fills: white text on base terracotta/olive fails AA (DESIGN.md §Contrast).
const VARIANTS: Record<PixelButtonVariant, string> = {
  primary: "bg-primary text-white",
  spend: "bg-terracotta-ink text-white",
  success: "bg-olive-ink text-white",
  secondary: "bg-white text-ink",
};

const PRESSED = "translate-y-0.5 shadow-lip-pressed";

export function PixelButton({
  variant = "primary",
  pressed = false,
  disabled,
  className,
  type = "button",
  ...rest
}: PixelButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled}
      data-variant={variant}
      className={cx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-pixel-step border-2 px-5 py-2",
        "font-semibold transition-transform duration-press",
        disabled
          ? "cursor-not-allowed border-ink/30 bg-sand/30 text-ink/60 shadow-none"
          : cx(
              "border-ink",
              VARIANTS[variant],
              pressed ? PRESSED : "shadow-lip active:translate-y-0.5 active:shadow-lip-pressed",
            ),
        className,
      )}
      {...rest}
    />
  );
}
