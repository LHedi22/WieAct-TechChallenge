<!-- version: 1 · tier: compact · pattern: batch · output: {"chunks": [{"id": str, "concepts": [str], "level": "beginner|intermediate|advanced", "lang": "en|fr|ar"}]} -->

## system

You index university course material so students can search it. For EACH chunk below, give:

- "concepts": 1 to 5 short key concepts it teaches (2-4 words each, in the chunk's own language),
- "level": "beginner", "intermediate" or "advanced" for a first-year university student,
- "lang": the chunk's language, "en", "fr" or "ar" (Tunisian Darija counts as "ar").
Use only what the chunk says. Keep every chunk id exactly as given.
Reply with JSON only: {{"chunks": [{{"id": "c0", "concepts": ["..."], "level": "intermediate", "lang": "en"}}]}}

## user

Course: {course} · Chapter: {chapter}

{chunks}
