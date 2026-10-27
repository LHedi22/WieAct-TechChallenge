import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "src/api/schema.d.ts"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      jsxA11y.flatConfigs.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // RTL: physical left/right utilities break Arabic layouts (CLAUDE.md rule 8).
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "Literal[value=/(^|\\s)-?(ml|mr|pl|pr|left|right|text-left|text-right|rounded-l|rounded-r|border-l|border-r)-/]",
          message: "Use logical utilities (ms-/me-/ps-/pe-/start-/end-/text-start) — RTL support.",
        },
        {
          selector: "Literal[value=/#[0-9a-fA-F]{6}\\b/]",
          message: "No raw hex in components: use Tailwind theme tokens from design/tokens.json.",
        },
      ],
    },
  },
  {
    files: ["**/*.js", "**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
);
