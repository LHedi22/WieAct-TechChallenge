<!-- version: 1 · shared rubric for teachback_grade and teachback_review (audit N-2: no anchor score) -->
Do NOT write a total score. Rate each criterion with an integer "level", judged against the
course excerpts; the server adds the levels up.
- "accuracy" 0-4: 0 = wrong, or says nothing true about the topic; 1 = mostly wrong, one right
idea; 2 = partly right with a clear mistake; 3 = right with a small slip or vague wording;
4 = fully right.
- "coverage" 0-3: the main ideas of the excerpts on this topic that it explains: 0 = none,
1 = one, 2 = most, 3 = all.
- "reasoning" 0-2: 0 = only names or defines; 1 = says how it works; 2 = says how AND why.
- "example" 0-1: 1 = a correct example or use of its own.
Never lower a level for spelling, grammar, the language used or a simple style: the same idea
gets the same levels in every language. A short explanation can be fully right.
Calibration (topic "how a thermometer works"; these are not about this course):
- "It measures heat." → {"accuracy": {"level": 1}, "coverage": {"level": 0}, "reasoning": {"level": 0}, "example": {"level": 0}}
- "The liquid in the tube expands when it gets warm, so it rises along the scale." → {"accuracy": {"level": 3}, "coverage": {"level": 2}, "reasoning": {"level": 1}, "example": {"level": 0}}
- "The liquid expands as it warms because its particles move faster and need more room, so the column rises; that is why it reads higher when you have a fever." → {"accuracy": {"level": 4}, "coverage": {"level": 3}, "reasoning": {"level": 2}, "example": {"level": 1}}
- "My team won the match yesterday." → "flag": "off_topic"
