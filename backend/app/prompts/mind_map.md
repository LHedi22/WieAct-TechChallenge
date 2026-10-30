<!-- version: 1 · tier: compact · pattern: execute-compact (from the mid notes) · output: {"root": str, "branches": [{"label": str, "children": [str]}]} -->

## system

Turn revision notes into a mind map: one central topic, 3-6 branches (the main ideas), each with
1-4 children (the details that hang on it). Every label is 1-6 words; no full sentences.
Use ONLY the notes below and keep their order.
Write everything in {language_name}. Write formulas between $ signs.
Reply with JSON only: {{"root": "...", "branches": [{{"label": "...", "children": ["..."]}}]}}

## user

Course: {course} · Chapter: {chapter}

{notes}
