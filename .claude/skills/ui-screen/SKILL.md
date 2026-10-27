---
name: ui-screen
description: Use when building or changing any frontend screen or component — map, island, building screens, onboarding, dialogs, edge-case screens. Covers design tokens, pixel-art rules, the mockup-fix list, RTL/i18n, accessibility and visual verification.
---

# Building a screen

1. **Find the reference.** Open the matching PNG in `design/mockups/` (or the page in
   `docs/reference/Learning_World_mockups.pdf`) and read `docs/DESIGN.md`, especially
   **§Mockup fixes** — those override the picture (coin numbers, costs, rewards, copy).
2. **Compose from primitives** in `frontend/src/components` (PixelButton, PixelPanel, SoftCard,
   Banner, Chip, counters, LoadingStages, Mascot). Add a new primitive to `/styleguide` before
   using it on a screen. Tailwind theme tokens only — no raw hex values in components.
3. **Data:** typed client from `src/api`; prices/rewards from `/api/economy`; AI work via `useJob`.
   Build the loading, empty, error, out-of-coins, queue, quick-mode and offline-demo states, not just the happy path.
4. **i18n:** every string in `src/i18n/{en,fr,ar,ar-TN}.json` (write real FR and AR, mark Darija
   strings `"_review": true` for native-speaker review). Logical properties only; wrap Latin
   fragments and numbers inside Arabic in `<Bidi>`.
5. **Pixel art:** sprites with `image-rendering: pixelated` at integer scales; text never in a pixel
   font; animations respect `prefers-reduced-motion` and the in-app reduced-motion setting.
   Calm study screens: no water animation, no mascot inside activities.
6. **Accessibility:** keyboard reachable, visible focus (sea ring), labels on icon buttons,
   AA contrast, list-view alternative for anything on the map.
7. **Verify visually:** run the app, open the screen at 1440×900 and at 390×844, in EN and AR.
   If a browser tool is available, screenshot and compare side by side with the mockup; list the
   differences you kept on purpose (because of Mockup fixes) in the PR/commit message.
