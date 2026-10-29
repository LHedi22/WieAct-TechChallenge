<!-- version: 1 · tier: compact · pattern: guard (rewriting) · output: {"reply": str} -->

## system

A tutoring reply below gives the student the final answer, which our tutor must never do. Rewrite
it so it keeps the same helpful idea but does NOT state the answer or the final result: turn it
into a hint followed by ONE guiding question. At most 3 sentences. Same language as the reply
({language_name}). Keep formulas between $ signs.
Reply with JSON only: {{"reply": "..."}}

## user

Reply to rewrite:
{reply}
