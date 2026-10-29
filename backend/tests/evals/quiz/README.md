# Quiz prompt eval (BUILD_PLAN M4)

Generate 20 questions per language from the seeded demo course and save them for review:

```bash
cd backend
uv run python -m app.seed --run                              # demo world OLIVE-7Q2, indexed
uv run python -m app.evals quiz --langs en,fr,ar --n 20      # LLM_PROVIDER decides mock/local/cloud
```

Each run writes `outputs/<provider>-<lang>.json`: every question, the excerpt chapter, and automatic
checks (valid structure, 4 distinct options, answer in range, script matches the language, the
concept appears in the excerpts, the hint does not name the correct option).

**Correctness review** (what the report needs): run against the real platform in our slot (or local
Ollama for a dry run), then fill `review.correct` (true/false) and `review.notes` for each question,
by hand or with the `prompt-evaluator` agent. Mock outputs only prove the pipeline: the mock writes
template questions, so its files are not a quality result.
