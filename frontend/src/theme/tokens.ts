// design/tokens.json is the single source of truth (also feeds tailwind.config.ts).
// Use Tailwind classes in components; read raw values here only where CSS classes can't reach
// (generated sprite placeholders).
import tokens from "../../../design/tokens.json";

export const color = tokens.color;
export default tokens;
