# Design system & screens

Mockups: `docs/reference/Learning_World_mockups.pdf` (19 frames) and per-screen PNGs in
`design/mockups/`. Style chosen in the mockups: **16-bit pixel art for the world, clean type for
everything you read.** This file overrides the mockups wherever they disagree.

## Tokens (also in `design/tokens.json` → `frontend/tailwind.config.ts`)
| Token | Hex | Use |
| --- | --- | --- |
| `whitewash` | #FAF7F2 | page background |
| `primary` (Sidi Bou Said) | #1F5FA8 | primary actions, links, selected |
| `sea` (teal) | #3BA3C7 | sea, focus rings |
| `terracotta` | #C8653A | spend/reward buttons, coins |
| `olive` | #6B7F3A | success |
| `sand` | #E9D8B4 | surfaces, soft-card borders |
| `ink` | #1E2A38 | text, pixel outlines |
| `danger` (soft red) | #C0443A | errors only |
Pixel art may add darker/lighter steps of each, plus cat orange and bougainvillea pink in small doses.

**Contrast (measured):** white on terracotta 3.9:1, terracotta on whitewash 3.65:1, white on olive
4.45:1, sea on whitewash 2.7:1 — all **fail AA for body text**. Use the `*-ink` shades from
`tokens.json` (terracotta-ink #A9502A 5.4:1, olive-ink #5F7134 5.4:1, sea-ink #1B7598 4.9:1) for
button fills with white text and for any text; keep base colors for fills, icons, the sea and large
headings. Primary blue with white text is fine (6.4:1).
Island accents: one per course from a fixed list of 6 (`island-1…6`), assigned in creation order.

Type: **Baloo Bhaijaan 2** 600 for headings (Display 64, H1 40, H2 28, H3 20);
**IBM Plex Sans Arabic** 400/600 for body (16/1.5) and small (13). Both via Google Fonts, both
cover Arabic. **Never a pixel font for text** — readability and Arabic shaping first.

## Components (build in `frontend/src/components`, show all in a `/styleguide` dev route)
- **PixelButton** — variants primary / spend (terracotta) / success / secondary; 2px stepped
  corners, 4px raised lip (box-shadow), pressed moves down 2px; focus ring sea; disabled.
- **PixelPanel** — ink outline, stepped corners: dialogs, map labels, focus surfaces.
- **SoftCard** — sand outline, rounded 8: lists, challenges, feeds.
- **Banner** — queue ("High demand…"), offline demo mode, quick mode, placement prompt.
- **Chip** — level, cost, Quick mode, Weak spot, Confidence, Pinned.
- **Counters** — coins, points, streak, refill timer (top bar); ProgressBar; SegmentedProgress (Q4/10); MasteryRing (island accent).
- **Input** — default, focused, error with message.
- **LoadingStages** — list of stages with done / in progress / next, plus WisdomTip card and mascot "thinking".
- **Mascot** — Sidi Bou Said cat, poses waving / reading / thinking / celebrating. Only on
  loading, empty states, tips, onboarding result — **never inside focused study screens**.

Icons: lantern = hint, lock, trophy, chest, coin, star (points), flame (streak), hourglass (refill).

## Pixel art implementation
- Sprites as PNG at 1× with `image-rendering: pixelated`, scaled by integer factors (2×/3×) only.
- Map: one `<svg>`/`<div>` scene with absolutely positioned island sprites over an animated water
  tile background (CSS `background-position` animation, disabled under `prefers-reduced-motion`).
- Island & building positions come from a layout JSON (`design/assets/layout.json`), not hard-coded
  per course — any number of courses (1–8) must lay out cleanly.
- Labels are HTML (PixelPanel) positioned over the scene so they translate and stay crisp.
- Until real sprites exist, use simple placeholder sprites (coloured blocks with outlines) behind
  the same component API, so art can be swapped without code changes. Source art: export from the
  mockup tool, or draw in Aseprite/Piskel at 16 px grid.

## RTL & i18n rules
- `dir` set on `<html>` from language (`ar`, `ar-TN` → rtl). Tailwind logical utilities only
  (`ms/me/ps/pe/start/end`, `text-start`). Mirror the layout: side panel moves to the left in RTL.
- Wrap Latin/numeric fragments inside Arabic text (`2B`, nicknames, scores like `7 / 10`, `(you)`)
  in `<bdi>` or the `<Bidi>` component — the RTL mockup shows "هندسة B2" and "(أنت)" broken.
- Numbers: Western digits everywhere (consistent with mockups); format with `Intl.NumberFormat`.
- Map scene itself is NOT mirrored (geography), but labels and panels are.

## Mockup fixes (implement these, not what the mockup shows)
1. **Coin amounts**: top bar shows 120 and "120 coins back in" → use `/api/economy`: 20 free/day.
   Empty-world screen shows 50 "Coins full" → same rule.
2. **Building costs on island**: Quiz 5 ✓, Socratic shows 3 → **8**, Study Studio 4 → **Free** if
   cached else **15** (generate), Audio 6 → **Free** if cached else **15**, Teach-Back 2 → label
   "Ask 2 · Answer free". Results "Go to the Socratic Tutor 3" → 8.
3. **Results "+12 coins"** for a quiz → quizzes earn **points only**; coins come from challenges
   and good peer answers (cap 10/day).
4. **Daily challenge rewards** shown as +15/+10/+20 with a coin icon → **+3 coins each** (and
   points, star icon). Out-of-coins "Finish today's challenges +45", "Keep your streak +30" → follow ECONOMY.md.
5. **Peer answer reward** "+5 coins" → **+3 coins** (and +30 points), only above score threshold.
6. **Exam Pass "unlimited buildings"** → "2 weeks · up to 15 AI activities a day". Never "unlimited".
7. **Coin pack** copy "50 coins, about 10 quizzes" ✓ keep.
8. **Island view "Click a building to walk there"** + avatar walking → decision was tap-to-enter,
   no walking: copy "Click a building to enter". Avatar can stand on the island as decoration.
9. **Map "Click an island to sail there"**: keep the sailing boat as a cosmetic animation (≤ 600 ms,
   skipped with reduced motion), then open the island.
10. **World created with 4 courses but map shows 5 islands** — demo seed must be consistent.
11. **RTL map**: island labels are hidden under island sprites and the avatar/boat label is missing
    — labels must sit in a reserved label slot with collision-free placement in both directions.
12. Results screen shows **offline demo mode banner** and **"+12 coins" earned** together — in
    offline mode nothing can be earned or spent; show saved results read-only.
13. Socratic "Show me the graph" — implement only as a static plot from a function expression
    (function-plot or a small SVG), else drop the button.
14. Add missing screens: placement quiz, daily return screen, Audio Studio, Teach-Back solo,
    sign-up form, revision notes and mind map tabs, admin/stats page (simple, for the report).

## Accessibility
List view of the whole map (keyboard navigable) is a first-class alternative. Visible focus
everywhere, contrast AA on all text (check terracotta on white for small text — use ink text on
terracotta buttons if needed), reduced-motion setting + media query, all icons have labels.

## Calm study screens
Inside buildings: whitewash background, no animated water, no mascot, game elements only at the
start (entry dialog) and end (results).
