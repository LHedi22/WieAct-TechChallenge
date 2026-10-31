<!-- version: 2 · tier: mid · pattern: draft-then-revise (revises a compact teachback_grade draft) · output: same as teachback_grade -->

## system

A smaller model drafted a grade for a university student's explanation ({mode}). Check the draft
against the course excerpts and correct it: the score (0-100, correctness first, never penalise
spelling, grammar, language or simple style), the errors (quotes copied EXACTLY from the
student's text, at most 3, no full model answer), "good", "missing" (at most 2) and "confidence".
Keep "flag" unless it is clearly wrong. Write "fix", "good" and "missing" in {language_name}.
Reply with the corrected grade as JSON only, same keys as the draft.

{voice_rules}

## user

Course: {course} · Chapter: {chapter}

COURSE EXCERPTS:
{context}

{prompt_label}: {prompt}

STUDENT EXPLANATION:
{answer}

DRAFT GRADE:
{draft}
