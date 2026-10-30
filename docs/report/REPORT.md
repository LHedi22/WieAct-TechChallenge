# Learning World — Phase 1 report (draft, ≤ 6 pages)

> Draft skeleton with the numbers measured so far. Items marked **[in-slot]** come from the real
> platform: `scripts/export_stats.py` after the user test, and the load run against cloud.
> Keep each section to about half a page.

## 1. Objective
Peer learning for university students in Tunisia, in the languages they actually study in (EN, FR,
MSA, Darija). One student uploads course material once; the class shares a world of islands
with five AI buildings. The AI asks before it tells (hints, Socratic questions) and turns shared
mistakes into anonymous tips.

## 2. Architecture
React (Vite) → FastAPI → Postgres job queue → one worker → AI gateway → EdNova platform.
Qdrant holds vectors, Postgres holds the text and everything else. Diagram: README → GenAI module.
Why a job per AI action: no streaming and several seconds of CPU latency, so the UI shows real
stages, queue position and ETA instead of a spinner.

## 3. Models and API use
Compact `llama3.2-3b`, mid `llama3.1-8b` (probe: 7/7 checks each, 2.5 s / 3.6 s median;
`docs/MODELS.md`). Routing table per task kind (ARCHITECTURE.md), with the four official patterns
and where each is used (README table). Calls per action: quiz set 1 compact · study pack 1 mid +
2 compact · audio 1 mid · tutor turn 1 compact (mid on escalation) · Teach-Back 1 compact (+ mid
review in the band) · tip 1 mid for every language of the class · daily plan 1 mid per student
per day.
Compact/mid split on our key: **[in-slot]**. Repeated identical requests: **[in-slot]** (0 in every
end-to-end run on the mock).

## 4. RAG workflow
Parsing (PDF/PPTX/DOCX/TXT/images, Tesseract `ara+fra+eng`) → page-bounded chunks with refs →
CHUNK_TAG (8 chunks per compact call) → embeddings (32 per call) → Qdrant with world/course/chapter
filters → narrow-before-generating at generation time. A 30-page PDF + a 12-slide PPTX cost 6 + 2
calls. Embeddings model on the platform: **OPEN** (DECISIONS.md).

## 5. Privacy and ethics
Nicknames only; no identity fields in the data model. Profile = level, style, goals. Moderation
on peer posts, no nicknames in tip prompts, synthetic or openly licensed demo data, key only in
`.env` and deploy secrets, gitleaks in CI. Tone doesn't change with level or language; the AI
supports teachers and doesn't replace them.

## 6. Testing strategy and results
- Gateway contract: one test per row of the error contract (quota, 503, 400 ceiling, 401, cache,
  malformed JSON → one repair call) against an in-process mock with fault injection.
- 260 backend tests, 64 frontend tests, mock-llm tests; i18n check (787 keys × 4 languages).
- End-to-end through the real UI per milestone (EN, FR, AR; 1440×900 and 390×844, RTL).
- Prompt eval on real outputs: **[in-slot]** (prompt-evaluator over `backend/tests/evals/`).
- User test with ~10 students at once: **[in-slot]**.

## 7. Limited-capacity handling
Priority lanes, 2-in-flight limiter, RPM bucket, quota delay → requeue with ETA, 503 → one retry
then compact (Quick mode), 400 → shrink once, cache-first shared outputs, single-flight,
precompute at upload on the background lane, offline demo mode outside our slot (cached results
only, no coins move). Load test: 30 jobs with 503 + quota faults, 30/30 done, ≤ 2 in flight,
interactive p50 38 s vs background 126 s (mock); against cloud: **[in-slot]**.

## 8. Business model
Target users: university students (first: engineering prep and bachelor's in Tunisia), then
teachers who seed a class. Value: shared, cached material makes each class's cost per student
fall as the class grows. Freemium: 20 coins/day free, cached class content always free; coin pack
(~2 TND) and a 2-week Exam Pass (~10 TND); a Class Pool lets students fund material together.
Adoption: one student creates the world and shares a join code. Sustainability: cost per class,
not per student (cache + compact-first routing). Prices to validate in user testing
(`docs/ECONOMY.md`).
