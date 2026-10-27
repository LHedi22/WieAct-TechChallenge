---
name: slot
description: Check whether the team's platform API key is live right now (time slots, Tunis time) and what that means for the work — /slot. Use before any in-slot task like GET /v1/models, prompt evals, load tests or demo recording.
---

# Slot check

1. Run `python3 scripts/slot.py` and report its output (live now? until when? next slot?).
2. If **live** and `docs/MODELS.md` has no "Probe results (cloud)" section yet, the first job is
   `python3 scripts/probe_models.py` (the human runs it; it reads `CLOUD_*` from `.env` itself).
   Then suggest the in-slot backlog from `docs/BUILD_PLAN.md` / `docs/DECISIONS.md` OPEN items
   that need the real platform (model names, quota headers, JSON mode, prompt evals, load test,
   demo recording), most valuable first. Remind that `.env` needs `CLOUD_API_KEY` set and
   `LLM_PROVIDER=cloud` or `auto` (`python scripts/llm.py use auto` once M1 is done) —
   the human edits `.env`, never Claude.
3. If **not live**: work against local Ollama (`LLM_PROVIDER=local`) if installed, else `mock-llm`;
   never retry the real platform in a loop.
