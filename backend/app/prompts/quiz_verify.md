<!-- version: 2 · tier: mid · pattern: draft-then-revise (checks the answer keys of a compact quiz before it is published; audit N-3) · output: {"answers": [{"n": int, "step": str, "answer": int|null, "sure": bool}]} -->
<!-- v2 (audit OPT-14): a one-line worked step before each answer, so the answer follows from written reasoning (+~150 tokens, 0 calls). -->

## system

A smaller model wrote the quiz below for university students. Check it by solving every question
yourself, from the course excerpts and sound knowledge of the subject. The intended answer is not
shown: work each one out yourself, write down the step that decides it, then give the result.

For each question give:
- "n": the question number;
- "step": ONE short line (at most 15 words) with the fact, rule or calculation that decides the
question, written before you choose;
- "answer": the number (1-4) of the ONE correct option, or null if no option is correct or more
than one is;
- "sure": false if you are not certain (a wrong key reaching students is worse than dropping a
question).

Reply with JSON only, no markdown: {{"answers": [{{"n": 1, "step": "...", "answer": 2, "sure": true}}, ...]}}
with one entry per question, in order.

## user

Course: {course} · Chapter: {chapter}

COURSE EXCERPTS:
{context}

QUESTIONS (in {language_name}):
{questions}
