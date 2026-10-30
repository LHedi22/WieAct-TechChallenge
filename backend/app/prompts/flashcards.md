<!-- version: 1 · tier: compact · pattern: execute-compact (from the mid notes) · output: {"cards": [{"front": str, "back": str, "concept": str}]} -->

## system

Turn revision notes into {count} flashcards for spaced repetition, for a {level} student.
Use ONLY the notes below. "front" is a short question or a term to recall (under 20 words);
"back" is the answer in one or two sentences (under 40 words). One idea per card, no card twice.
"concept" is the course concept the card tests, 1-4 words.
Write everything in {language_name}. Write formulas between $ signs.
Reply with JSON only: {{"cards": [{{"front": "...", "back": "...", "concept": "..."}}]}}

## user

Course: {course} · Chapter: {chapter}

{notes}
