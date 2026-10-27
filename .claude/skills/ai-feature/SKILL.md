---
name: ai-feature
description: Use whenever you add or change anything that calls the LLM or embeddings — a new building feature, a new prompt, a new TaskKind, grading, tagging, generation. Walks through routing, caching, jobs, coins, prompts, i18n and tests so the feature respects the platform constraints.
---

# Adding an AI feature

Read `docs/PLATFORM.md` and the routing table in `docs/ARCHITECTURE.md` first.

## 1. Decide the task shape (write it in the plan)
- **TaskKind** name, **tier** (compact by default — justify every mid-size use in one line), and
  the official **pattern**: escalation / draft-then-revise / plan-once-execute-compact /
  narrow-before-generating / triage / fallback.
- **Lane:** `interactive` (a student is waiting) or `background` (precompute, tagging, tips).
- **Calls per user action:** aim for ONE. Batch (10 questions in one call, many chunks per tag call).
- **Cache key:** what makes two requests "equivalent"? Shareable outputs key on
  `world_id, chapter_id, level, language (+ prompt version)`. Personal/conversational → `None`.
- **Coin cost** from `economy.py` (add a constant if new; never inline a number). Cached → 0.

## 2. Prompt
- New file `backend/app/prompts/<task_kind>.md` with a header comment: version, tier, pattern, output schema.
- System prompt states: role, the hint-first / no-final-answer rule where relevant, reply language
  `{language}` (support `en`, `fr`, `ar`, `ar-TN` Darija in Arabic script), learner level and style.
- Ground in retrieved chunks: `{context}` with page/slide refs; tell the model to say when the
  material doesn't cover the question instead of inventing.
- Ask for **strict JSON** matching a Pydantic model in the feature module. Keep outputs short —
  there is a max response length ceiling.
- No personal data in prompts — nicknames only when needed, never anything else.

## 3. Wire it
```
features/<x>/service.py   → builds Task(kind, lane, messages, language, cache_key, max_tokens)
                          → result = await gateway.run(task)    # never import openai here
features/<x>/jobs.py      → job handler; set job.stage before each step for the loading screen
features/<x>/router.py    → POST creates job (reserve coins) or returns cached result (cost 0)
```
- Stages: human-readable keys added to all four locale files (`jobs.stage.<key>`).
- On failure: refund coins, job `failed` with a user-safe message key, never a raw model error.
- If the result can be `quick_mode`, the UI must show the Quick mode chip.

## 4. Frontend
- Use `useJob(jobId)`; render `LoadingStages` with a Class Wisdom tip; show queue position/ETA,
  quick-mode badge, "Cancel and keep my coins".
- All strings via i18n; check the screen in Arabic (RTL).

## 5. Tests (write first)
- Unit: prompt builder output, JSON parsing + repair, cache-key equivalence.
- Gateway behaviour with mock faults: `503` → fallback, quota → requeue, `400` → shrink once.
- An eval fixture in `backend/tests/evals/<task_kind>/` with 3–5 real inputs per language; run
  `uv run python -m app.evals <task_kind>` in-slot and save outputs for the report.

## 6. Log it
Add a row to the routing table in ARCHITECTURE.md if the TaskKind is new, and a line in DECISIONS.md
for any tier choice that isn't obvious.
