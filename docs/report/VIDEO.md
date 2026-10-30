# Demo video — shot list (≤ 1:30)

Record in our slot on the deployed site, by **Mon 9/11**. No key, `.env` or admin token on screen.
Screen 1440×900; one phone-size shot in Arabic.

| Time | Shot | Shows |
| --- | --- | --- |
| 0:00–0:10 | Landing → language picker → map of the demo world | Concept, 4 languages |
| 0:10–0:22 | Second browser joins with code `OLIVE-7Q2`; same islands, presence | Shared world |
| 0:22–0:40 | Quiz Hall: loading stages with **queue position + ETA** (run `scripts/load.py` on the side) → wrong answer → hint → second try | Queueing, hints before answers |
| 0:40–0:55 | Socratic Tutor: "I'm stuck" ×2 → mid turn; a saturated moment shows the **Quick mode** badge | Escalation, fallback |
| 0:55–1:08 | Loading screen with a **Class Wisdom tip**; Teach-Back answer scored, asker pins it | Peer learning, anonymous tips |
| 1:08–1:20 | Arabic (RTL) on a phone: Study Studio pack opens free ("your class already made one") | Multilingual, cache |
| 1:20–1:30 | `docs/report/stats-cloud-*.md` (from `/api/admin/stats`): compact/mid split, cache hits, 0 repeated identical, refusals handled | Orchestration and constraint evidence |

If the slot isn't live while recording, show the **offline demo mode** banner for 3 seconds
instead of the queue shot: saved results open and new AI actions are paused.
