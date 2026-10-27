# Coin & point economy

**Single source of truth in code: `backend/app/core/economy.py`**, exposed at `GET /api/economy`.
The frontend renders every price/reward from that endpoint. Numbers below are the decided starting
values; the mockups show placeholder numbers that are WRONG where they differ (see DESIGN.md §Mockup fixes).

## Principles
- **Coins** are spent on AI activities. **Points** are earned for learning, drive leaderboards and
  unlock cosmetics. Points can never be bought; coins never buy rank or cosmetics.
- Price follows compute: personalised, AI-heavy = expensive; reusing what the class already made = free.
- Free coins cover a normal study day, not an exam day.

## Constants
```python
DAILY_FREE_COINS = 20            # refilled at local midnight (Africa/Tunis); unused free coins do NOT carry over
DAILY_EARN_CAP = 10              # max coins earned per day from challenges + peer answers
PURCHASED_COINS_EXPIRE = False

COST = {
    "cached_content": 0,         # reopen notes, flashcards, maps, audio, past quizzes
    "flashcard_review": 0,
    "placement_quiz": 0,         # 8 questions, once per course
    "quiz": 5,                   # 10 questions
    "tutor_session": 8,
    "teachback_solo": 8,
    "generate_shared_asset": 15, # new notes / map / audio for a chapter+level+language; Class Pool can pay
    "peer_question": 2,
}
EARN = {
    "peer_answer_good": 3,       # only if AI score >= PEER_ANSWER_THRESHOLD
    "daily_challenge": 3,        # each, 3 per day
}
PEER_ANSWER_THRESHOLD = 70       # /100
WISDOM_THRESHOLD = 3             # distinct students with the same (concept, mistake_type) in a world

POINTS = {
    "quiz_correct_first_try": 10,
    "quiz_correct_second_try": 5,   # "half the points"
    "activity_completed": 20,
    "peer_answer_good": 30,
    "pinned_best_answer": 50,
    "daily_challenge": 15,
    "all_challenges_bonus": 30,     # streak bonus when all 3 are done
    "teachback_solo_per_10_score": 3,
}
SPENDING_ORDER = ["free", "earned", "purchased"]   # burn expiring coins first
```

## Wallet rules
- Coin buckets: `free_today` (resets daily), `earned` (capped per day, persists), `purchased` (never expires).
- Reserve coins when a job is created; commit on success; **refund on failure or cancel**
  ("Cancel and keep my coins" on the queue screen).
- If the result is served from cache, charge **0** even for a normally paid activity — the API
  tells the UI `cached=true` before the user confirms.
- Exam Pass active → activities cost 0 up to `EXAM_PASS_DAILY_LIMIT = 15` AI activities/day
  (a *high daily limit*, never "unlimited" — the platform quota is finite).
- Class Pool: members transfer coins to `class_pool`; shared asset generation can be paid from it.
- Creator reward: +5 coins (counts toward the daily earn cap) when a new member joins and completes
  a first activity in their world.

## Day examples (for the report)
- Normal day: 1 quiz (5) + 1 tutor (8) = 13 ≤ 20 free.
- Exam day: 4 quizzes (20) + 3 tutor (24) + 2 solo (16) = 60 → 20 free + 10 earned = 30 short → purchase.

## Products (prices are placeholders to validate in user testing)
| Product | Gives | Price |
| --- | --- | --- |
| Free tier | 20 coins/day, cached class content always free | 0 TND |
| Coin pack | 50 coins, never expire (~10 quizzes) | ~2 TND |
| Exam Pass | 2 weeks, 15 AI activities/day at 0 coins | ~10 TND |

**For the hackathon, purchases are simulated** (a "demo purchase" button that credits coins and is
clearly labelled). Konnect / D17 integration is described in the business note, not built.

Fairness: no ads; rank can't be bought; nothing free is ever moved behind payment.
