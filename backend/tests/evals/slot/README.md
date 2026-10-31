# In-slot run (STATUS.md §2)

Every AI feature students use, in `en`, `fr`, `ar` and `ar-TN`, on the demo world, saved for review:

```bash
docker compose exec backend uv run python -m app.evals slot            # mock or local: free
docker compose exec backend uv run python -m app.evals slot --cloud    # in our slot (/slot) only
python3 scripts/export_stats.py --provider cloud                       # on the host, afterwards
```

Per language: one Study Studio pack (notes, mind map, flashcards), one Audio episode, the daily
plan, two Teach-Back solo answers (a solid one and a partial one). Then one Class Wisdom tip for a
new trap shared by three synthetic classmates (one mid call writes it in all four languages).
About 30 calls on the cloud, 17 of them mid; the gateway paces them (2 in flight, `LLM_MAX_RPM`).

Writes `outputs/<provider>-<task>-<lang>.json`. Mock and local files are gitignored; cloud files are
committed for the report. Each has an empty `review` (`verdict`, `notes`) for the
`prompt-evaluator` agent or a person: correctness against the slides, grounding, language
(Tunisian Darija, not MSA or Egyptian, for `ar-TN`), level fit, tone, and for Teach-Back whether the
solid answer scored clearly above the partial one.

Shared outputs are made once per chapter, level and language. `"cached": true` means no call was
made, and on a dev database the cached text may come from the mock, so the run uses
`--level advanced` by default. Teach-Back grades are reused from this provider's saved file
(grading is personal and never cached, so resending would be a repeated identical request);
`--regrade` sends them again.
