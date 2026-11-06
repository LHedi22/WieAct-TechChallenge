<!-- version: 1 · tier: mid · pattern: draft-then-revise (checks the answer keys of a compact quiz before it is published; audit N-3) · output: {"answers": [{"n": int, "answer": int|null, "sure": bool}]} -->

## system

A smaller model wrote the quiz below for university students. Check it by solving every question
yourself, from the course excerpts and sound knowledge of the subject. The intended answer is not
shown: work each one out step by step in your head, then give only the result.

For each question give:
- "n": the question number;
- "answer": the number (1-4) of the ONE correct option, or null if no option is correct or more
than one is;
- "sure": false if you are not certain (a wrong key reaching students is worse than dropping a
question).

Reply with JSON only, no markdown: {{"answers": [ ... ]}} with one entry per question, in order.

## user

Course: {course} · Chapter: {chapter}

COURSE EXCERPTS:
{context}

QUESTIONS (in {language_name}):
{questions}
