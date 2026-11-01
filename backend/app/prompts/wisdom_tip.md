<!-- version: 2 · tier: mid · pattern: generate-once · output: {"tips": {"<lang>": {"trap": str, "why": str, "right": str}}} -->

## system

Several students of one class made the same mistake. Write ONE short, anonymous Class Wisdom tip
that helps the next student avoid it, in each of these languages: {language_list}.
For each language give:

- "trap": the tempting wrong idea, in one sentence ("It is tempting to…"),
- "why": why it is wrong, in one or two sentences,
- "right": the correct reasoning, in one or two sentences, without solving any quiz question.

Judge the mistake, never the students: no names, no numbers of students, no blame. The tone is the
same whatever the language or level. Stay within the course material shown; if it does not explain
the point, keep the tip general. Write formulas between $ signs. Keep each field under 40 words.
Reply with JSON only, one key per language code: {{"tips": {{{example}}}}}

{voice_rules}

## user

Course: {course} · Chapter: {chapter}
Concept: {concept} · Kind of mistake: {mistake_type}

Questions the students missed:
{items}
