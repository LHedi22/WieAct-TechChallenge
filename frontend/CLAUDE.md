# Frontend (React + Vite + TS) — local rules

- pnpm only. TypeScript strict. React Router, TanStack Query for server state (polling via `refetchInterval`), Zustand only for UI state (language, reduced motion, map/list view).
- Tailwind with tokens from `design/tokens.json` (see `tailwind.config.ts`); no raw hex in components. Logical utilities only (`ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-`, `text-start`).
- API types generated from the backend: `pnpm api:gen` (openapi-typescript against `http://localhost:8000/openapi.json`) → `src/api/schema.d.ts`. Don't hand-write response types.
- i18n: react-i18next, namespaces per feature, ICU plurals. Files `src/i18n/{en,fr,ar,ar-TN}.json`. `pnpm i18n:check` fails on missing keys. Language → `document.documentElement.dir/lang`.
- Fonts via Google Fonts: Baloo Bhaijaan 2 (600), IBM Plex Sans Arabic (400, 600).
- Animations: Framer Motion; respect `useReducedMotion()` and the app setting.
- Math: KaTeX. Mind maps: SVG renderer from JSON tree (Mermaid acceptable).
- AI actions: always `useJob(jobId)` → `LoadingStages`; never block the UI with a spinner alone.
- `VITE_API_URL` is the only env var the frontend reads. Nothing about the LLM exists here.
- Tests: Vitest + Testing Library; Playwright smoke in `e2e/` (landing → first quiz, EN and AR).
