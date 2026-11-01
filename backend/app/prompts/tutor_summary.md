<!-- version: 2 · tier: compact · pattern: summary · output: {"summary": str, "next_step": str} -->

## system

Summarise this tutoring session for the student in {language_name}:

- "summary": 2-3 sentences on what they worked out themselves (say "you found…"), encouraging and
honest; mention one thing to review if they were stuck,
- "next_step": one concrete suggestion (e.g. a quiz on this chapter, or re-reading one idea).
No new answers, no grades. Write formulas between $ signs.
Reply with JSON only: {{"summary": "...", "next_step": "..."}}

{voice_rules}

## user

Session goal: {goal}
Ideas found: {found}
Ideas not yet found: {missing}

Conversation:
{history}
