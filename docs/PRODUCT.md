# Product — Learning World (working name)

A university student's courses become islands in a shared archipelago ("world") for their class.
Each island has the same five buildings, all grounded in that course's uploaded material.
The AI guides rather than answers: hints before answers, questions instead of solutions, rewards
for explaining to others. Target: landing → first quiz in **under 5 minutes**. Desktop-first
(1440×900), usable on phones (side panel becomes a drawer).

## Challenge fit (keep visible in the demo)
| EdNova goal | Feature |
| --- | --- |
| Explain simply, guiding questions, hints before answers, detect confusion, suggest next step | Socratic Tutor, Quiz Hall hints + explanations, mistake tags → weak spots, results "next step" |
| Diagnostic step → learning style & level | Onboarding style test + per-course placement quiz; profile keeps updating |
| Peer learning, group balance, ask without fear of judgment | Shared worlds, Teach-Back peer room (nicknames, AI-scored), anonymous Class Wisdom |
| Arabic, Darija, French, English | UI + all AI output in 4 languages, RTL for Arabic/Darija |
| Open innovation | Gamified world, revision notes, collaborative explanations, learning analytics |
| Entrepreneurship | Freemium coins + Exam Pass (ECONOMY.md) |

## Screens & flow
1. **Landing** — one-line promise, sample-world preview, Start button, language picker (EN/FR/العربية/Darija). Arabic & Darija → RTL.
2. **Sign up** — nickname + password only (no Google, no email). Nickname helper: "No real names or photos."
3. **Style test** (staged, progress bar "Step n of 5"): profile (university, field, year, courses + exam dates), 4–6 scenario cards ("You're learning a new formula, you'd rather…" → visual / practice / listening / teaching), goals per course (pass / target grade / deep understanding), daily study time + reminder time, language(s), leaderboard opt-in. "Skip for now" allowed.
4. **Result card + avatar** — style mix percentages + where we'll point them first; DiceBear-style pixel avatar: skin tone, outfit, extras (some free, some locked by points).
5. **Create or join** — join by code (`OLIVE-7Q2` format) or invite link; create wizard: name → courses → chapters → upload files per chapter (PDF, PPTX, DOCX, images, TXT; 50 MB max) → staged indexing screen with class code and share button.
6. **World map** — islands (one per course, accent color, mastery ring); top bar: coins, points, streak, refill timer, avatar; side panel: 3 daily challenges + class leaderboard. Map/List toggle, zoom. Island locked (grey) until placement quiz.
7. **Island view** — 5 buildings with coin cost (from `/api/economy`, 0 shown as "Free" when cached), chapters with mastery & weak-spot chips, "on this island now" (classmates studying, polling), placement banner if level not set.
8. **Building entry dialog** — pick chapter + level (Beginner / Intermediate / Advanced), cost and balance after, Confirm.
9. **Loading screen** — real staged steps from the job, queue position / ETA when queued, quick-mode notice, Class Wisdom tip ("Show me another tip"), "Cancel and keep my coins".
10. **Activity** (see buildings).
11. **Results** — score, each mistake with explanation, coins/points earned, streak, ONE suggested next step (deep link), "Turn these into flashcards".
12. **Daily return** — first open of the day: refilled coins, streak, 3 challenges → map.
13. **Edge screens** — out of coins; quick mode / queue; empty world ("This world is still all sea"); island awaiting placement; offline demo mode banner.

## The five buildings
### Quiz Hall (El Jem amphitheatre)
10 questions generated in ONE call from retrieved chunks at the chosen level/language. One question
per screen. Wrong → feedback + **hint** + second try (half points) → then correct answer +
explanation. "Save and exit". Every wrong answer is tagged (concept, mistake_type) → weak spots,
challenges, Class Wisdom. Question types: MCQ (4 options) for v1; math rendered with KaTeX.

### Socratic Tutor (blue-door café)
Chat that **never gives the final answer**. Session goal shown in a side panel, hints used (max 3),
"Ideas you've found" checklist. Buttons: Give me a hint · Explain it another way · I'm stuck.
Escalates to mid-size after 2 stuck signals or when the compact model flags the topic complex.
Adapts style (analogies for beginners, examples for practice learners, diagrams-in-words for
visual). If confidence is low → suggest asking the teacher. End → session summary.
A guard step checks each compact reply for leaked final answers; if leaked, rewrite as a question.

### Study Studio (domed medina library)
Tabs: Revision notes (at level) · Flashcards (spaced repetition: Again <1 min, Good 10 min, Easy 3 days; keyboard 1/2/3, Space flips) · Mind map (render JSON tree as SVG/Mermaid).
Generated once per world+chapter+level+language, then free for the class.

### Audio Studio (music house with an oud) — first to cut
Mid-size writes a short podcast script per chapter; played with Web Speech API (ar, fr, en),
transcript + speed control. Darija: silma-tts-derja pregenerated (declared service) or transcript only.

### Teach-Back Arena (Carthage columns) — central to the demo
- **Peer room:** question feed per chapter; ask (2 coins, compact moderation first); classmates
  answer; AI scores each answer (score /100, confidence, errors, "Good:" line); answers ≥ threshold
  earn coins + points; best answer pinned; "helpful" votes; "Improve my answer". If no peer answers
  within 10 min the asker can ask the AI (Socratic style).
- **Solo mode:** explain a concept → score, confidence, mistakes, what was missing.

## Daily challenges
3 per student per day, planned by ONE mid-size call at first login (weak topics, style, goals,
exam dates), saved for the day; compact generates any needed items. Types: answer N quiz
questions, review N flashcards, explain one idea in Teach-Back, fix weakest flashcards, score X%
on chapter quiz. All 3 → streak bonus. Reminder at chosen time (in-app; email/push out of scope).

## Class Wisdom
After each quiz, compact tags wrong answers. Count distinct students per (world, concept,
mistake_type). At threshold (3), mid-size writes one anonymous tip: the trap, why it's wrong, the
right reasoning. Shown on loading screens and in Quiz Hall. "Names are hidden. Only the pattern is shared."

## Leaderboards, streaks, badges, cosmetics
Per world and global, weekly and all-time, opt-out respected (shown as "Hidden explorer" or excluded).
Badges: chapter mastery, Mentor (top-rated peer answers). Cosmetics unlocked by points only.

## Privacy & ethics (enforced in code review)
Nicknames only; no real names, photos, age, gender, addresses, voices. Profile = level, style,
goals only, so the AI cannot treat students differently by gender, region, language level or
background. Shared content anonymous. Demo material public/synthetic/openly licensed only.
Moderation on peer posts. "Ask your teacher" suggestion when AI confidence is low.

## Languages
`en`, `fr`, `ar` (MSA), `ar-TN` (Darija, Arabic script, RTL). UI language and content language
are separate settings; compact detects message language and replies in it. Darija outputs must be
reviewed by native speakers before the demo.
