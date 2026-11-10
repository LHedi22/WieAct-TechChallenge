# Demo video — notes (10 Nov 2026)

`final.mp4` and `final-subtitled.mp4`: 90.0 s, 1920×1080, H.264 High + AAC LC (48 kHz), about
18–19 MB, voiceover at −16.4 LUFS. The subtitled version burns the voiceover text in (yellow,
bottom centre). `contact-sheet.png` has one frame every 2 s.

## How it was made
- **Recorded on the local stack, not the platform.** Our slots had ended and there is no deployed
  site yet, so every AI output on screen comes from our own Ollama models: compact `qwen3:1.7b`,
  mid `llama3.2:3b` and embeddings from `bge-m3`. A small note in the bottom-right corner says so
  for the whole video, and the app's own "Test data (local)" chip is left visible on generated
  content. The stats page (shot 13) shows provider = local, with the in-slot cloud figures in its
  subtitle.
- **Recording-only config** (`scripts/video/compose.video.yml`):
  - The interactive mid budget goes from 45 s to 150 s.
  - The local mid model is `llama3.2:3b` instead of `qwen3:8b`. With Docker and Chromium also
    running, `qwen3:8b` ran the 15 GB laptop out of memory: Docker hung once, and Claude Code
    killed two recordings.
  - The stack was set back to normal afterwards.
- **Data:** `scripts/video/prepare.py` drives the real API and job pipeline. It creates world
  TIDES-BBW and four synthetic explorers: Amira (A, EN), Youssef (B, AR), Sami (C, EN) and Lina
  (D, AR). It also does placements, a Class Wisdom tip from three synthetic students, packs and
  C's Teach-Back question. Two half-made duplicate worlds (CORAL-GGT, REEFS-TH2) from a runaway
  retry are still in the dev DB: deleting them was blocked by the permission check.
- **Recording:** `scripts/video/record.ts` (Playwright, one test per shot,
  `cd scripts/video && node node_modules/@playwright/test/cli.js test -c playwright.config.ts -g <shot>`).
  - Desktop shots after 03 were recorded at deviceScaleFactor 1 to save memory, so they are softer
    than 01–03. Phone shot: 390×844, scale factor 2.
  - Attempts are logged in `raw/attempts.log`.
- **Edit:** `bash scripts/video/edit.sh`, which runs `voiceover.py` (edge-tts, en-US-AndrewNeural)
  and `edit.py`, driven by `scripts/video/timeline.json`. There is no music
  (`docs/report/video/music.mp3` is absent).

## Shots
| Time | Shot | Shows | Notes |
| --- | --- | --- | --- |
| 0:00 | 01 landing | EN → FR → العربية → Darija, RTL flip | the Arabic flip plays at 1× |
| 0:05 | 02 onboarding | nickname sign-up, style test, result %, avatar "Surprise me" | |
| 0:12 | 03 side by side | A builds the world (wizard, upload, indexing, code) · B joins with TIDES-BBW in Arabic | indexing was sped up 190× |
| 0:18 | 04 map | islands with mastery rings, coins/points/streak, daily challenges, class list | the leaderboard page was too sparse to use |
| 0:24 | 05 island | five buildings, "On this island now · 2 classmates" | there is no separate placement-banner shot |
| 0:29 | 06 loading | dialog (level + coins), "number 1 in line (about 22 s)", Class Wisdom tip | a real job; a classmate's quiz was queued first |
| 0:33 | 07 Quiz Hall | wrong → hint → right on the 2nd try → score 8/9, next step, "Turn these into flashcards", Class Wisdom card | the class's cached intermediate set |
| 0:45 | 08 Tutor | message → reply, "I'm stuck" ×2, the 2nd reply on the mid model (escalation), ideas ticking | the answer guard rewrote one reply |
| 0:57 | 09 + 10 | EN Study Studio (free: "your class already made one"), notes, flashcards flip/grade · phone: Arabic pack opens free | |
| 1:05 | 11 Audio | episode playing (real Windows voices, headed Chromium) | |
| 1:09 | 12 Teach-Back | explanation → queue + tip → mid double-check → 80/100 → "Pinned as best" | recovered from attempt 1 (the script crashed after the pin; the app was fine) |
| 1:19 | 13 stats | AI usage report from `/api/admin/stats` (local) + 2 s of the offline banner | the offline switch was set back to auto |
| 1:26 | end card | name, tagline, QR + github.com/LHedi22/WieAct-TechChallenge | |

## Cut or changed
- **Mind maps:** not shown. Every local MAP_WRITE output failed validation, so voiceover line 8
  now says "Notes and flashcards…".
- **Advanced-level packs:** failed, because the compact fallback's notes were cut off at the
  700-token budget (BadOutput). The Studio shots use the intermediate packs instead.
- **Queue shot:** filmed on the Studio generate screen, because the Tutor start has no tip.

## Weak spots — re-record by hand if there's time
1. **Model quality:** these are local small models, not the platform's.
   - Shot 07's hint says the limit "approaches 1/2" for a question whose key is "0/0" (a muddled
     question).
   - The tutor drifts from sin x/x to factoring.
   - Re-recording on the platform (Widened tier) would fix both.
2. **Arabic phone notes:** the maths shows as "extlim… ↑racx²". LaTeX `\t`/`\f` in the model's
   JSON were decoded as tab and form-feed characters. This is a real bug in JSON parsing or prompt
   escaping; it's on screen for about 2 s at phone size.
3. **Resolution and stats:**
   - Desktop shots from 04 onward were recorded at scale factor 1, so small text is soft. Re-record
     on a machine with more RAM at scale factor 2 for crisper text.
   - The stats page shows "Repeated identical 10" (real, from today's retries on local models).
