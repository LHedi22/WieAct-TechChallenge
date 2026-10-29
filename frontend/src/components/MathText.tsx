import { Fragment, type ReactNode } from "react";
import { cx } from "./cx";

/**
 * Text with inline math between `$…$` (how the prompts ask the model to write formulas).
 * A small built-in renderer for the LaTeX that course questions use — \lim, \frac, ^ and _,
 * \to, \infty, \sqrt, \cdot, comparisons and Greek letters — so no extra dependency is needed
 * (KaTeX could not be installed from this network; it can replace this later behind the same API).
 * Math is always laid out left to right, also inside Arabic text.
 */
export function MathText({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/(\$[^$]+\$)/g);
  return (
    <span className={className}>
      {parts.map((part, i) =>
        part.length > 2 && part.startsWith("$") && part.endsWith("$") ? (
          <bdi key={i} dir="ltr" className="math whitespace-nowrap font-semibold">
            {renderTex(part.slice(1, -1))}
          </bdi>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </span>
  );
}

const SYMBOLS: Record<string, string> = {
  to: "→",
  infty: "∞",
  cdot: "·",
  times: "×",
  le: "≤",
  leq: "≤",
  ge: "≥",
  geq: "≥",
  ne: "≠",
  neq: "≠",
  approx: "≈",
  pm: "±",
  alpha: "α",
  beta: "β",
  gamma: "γ",
  delta: "δ",
  Delta: "Δ",
  epsilon: "ε",
  theta: "θ",
  lambda: "λ",
  mu: "μ",
  pi: "π",
  sigma: "σ",
  Sigma: "Σ",
  phi: "φ",
  omega: "ω",
  in: "∈",
  sum: "Σ",
  int: "∫",
  left: "",
  right: "",
  quad: " ",
};
const WORDS = new Set(["lim", "sin", "cos", "tan", "ln", "log", "exp", "max", "min"]);

/** Parse one `$…$` body into React nodes (tolerant: unknown commands are shown as written). */
function renderTex(src: string): ReactNode[] {
  let pos = 0;
  const out: ReactNode[] = [];
  let key = 0;

  const group = (): string => {
    // {…} with nesting, or a single character / command
    while (src[pos] === " ") pos++;
    if (src[pos] === "{") {
      let depth = 0;
      const start = pos + 1;
      for (; pos < src.length; pos++) {
        if (src[pos] === "{") depth++;
        else if (src[pos] === "}" && --depth === 0) break;
      }
      const body = src.slice(start, pos);
      pos++;
      return body;
    }
    if (src[pos] === "\\") {
      const m = /^\\[a-zA-Z]+/.exec(src.slice(pos));
      if (m) {
        pos += m[0].length;
        return m[0];
      }
    }
    return src[pos++] ?? "";
  };

  while (pos < src.length) {
    const ch = src[pos]!;
    if (ch === "\\") {
      const m = /^\\([a-zA-Z]+)/.exec(src.slice(pos));
      if (!m) {
        out.push(src[pos + 1] ?? "");
        pos += 2;
        continue;
      }
      const name = m[1]!;
      pos += m[0].length;
      if (name === "frac") {
        const num = group();
        const den = group();
        out.push(
          <span
            key={key++}
            className="inline-flex flex-col items-center px-0.5 align-middle text-[0.85em] leading-tight"
          >
            <span className="border-b border-current px-0.5">{renderTex(num)}</span>
            <span className="px-0.5">{renderTex(den)}</span>
          </span>,
        );
      } else if (name === "sqrt") {
        out.push(
          <span key={key++}>
            √<span className="border-t border-current">{renderTex(group())}</span>
          </span>,
        );
      } else if (WORDS.has(name)) {
        out.push(
          <span key={key++} className="font-normal not-italic">
            {name}
          </span>,
        );
      } else {
        out.push(SYMBOLS[name] ?? `\\${name}`);
      }
      continue;
    }
    if (ch === "^" || ch === "_") {
      pos++;
      const body = group();
      const Tag = ch === "^" ? "sup" : "sub";
      out.push(<Tag key={key++}>{renderTex(body)}</Tag>);
      continue;
    }
    if (ch === "{" || ch === "}") {
      pos++;
      continue;
    }
    // runs of plain characters; letters in italics like math variables
    const m = /^[^\\^_{}]+/.exec(src.slice(pos))!;
    pos += m[0].length;
    for (const piece of m[0].split(/([a-zA-Z]+)/)) {
      if (!piece) continue;
      out.push(
        /^[a-zA-Z]+$/.test(piece) ? (
          <i key={key++} className={cx("font-serif")}>
            {piece}
          </i>
        ) : (
          piece
        ),
      );
    }
  }
  return out;
}
