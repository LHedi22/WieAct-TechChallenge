"""The challenge catalogue, the rule-based plan (instant, no AI) and validation of the DAILY_PLAN
output. Pure functions: everything the database knows comes in as `Candidate`s."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

ChallengeType = Literal["quiz_questions", "quiz_score", "teachback", "tutor_session", "flashcards"]
TYPES: tuple[str, ...] = (
    "quiz_questions",
    "quiz_score",
    "teachback",
    "tutor_session",
    "flashcards",
)
TARGETS: dict[str, tuple[int, ...]] = {
    "quiz_questions": (5, 10, 15, 20),
    "quiz_score": (60, 70, 80, 90),  # percent on one chapter quiz
    "teachback": (1,),
    "tutor_session": (1,),
    "flashcards": (10, 20),  # cards reviewed in the Study Studio
}
NEEDS_CHAPTER = {"quiz_score"}
COUNT = 3


@dataclass(frozen=True)
class Candidate:
    """A chapter the student can work on today (their worlds, placed or not)."""

    world_id: uuid.UUID
    course_id: uuid.UUID
    chapter_id: uuid.UUID
    course: str
    chapter: str
    mastery: int | None  # None = never quizzed
    weak: bool
    exam_date: date | None


def _snap(kind: str, target: int) -> int:
    """The allowed target nearest to what was asked."""
    return min(TARGETS[kind], key=lambda t: (abs(t - target), t))


def challenge(kind: str, target: int, c: Candidate | None, why: str | None = None) -> dict:
    return {
        "type": kind,
        "target": _snap(kind, target),
        "progress": 0,
        "done": False,
        "why": why,
        "world_id": str(c.world_id) if c else None,
        "course_id": str(c.course_id) if c else None,
        "chapter_id": str(c.chapter_id) if c else None,
        "course": c.course if c else None,
        "chapter": c.chapter if c else None,
    }


def ranked(cands: list[Candidate], today: date) -> list[Candidate]:
    """Weak first, then nearest exam, then lowest mastery (unquizzed count as 50)."""

    def key(c: Candidate) -> tuple:
        days = (c.exam_date - today).days if c.exam_date and c.exam_date >= today else 999
        return (not c.weak, days, c.mastery if c.mastery is not None else 50, c.course, c.chapter)

    return sorted(cands, key=key)


def rule_plan(cands: list[Candidate], today: date, style_teaching: int = 25) -> list[dict]:
    """Instant plan: 10 questions, 70 % on the weakest chapter, then explain or get tutored."""
    order = ranked(cands, today)
    first = order[0] if order else None
    third = "tutor_session" if first and first.weak and style_teaching < 40 else "teachback"
    out = [
        challenge("quiz_questions", 10, first),
        challenge("quiz_score", 70, first) if first else challenge("quiz_questions", 5, None),
        challenge(third, 1, first),
    ]
    return out


class AIChallenge(BaseModel):
    type: ChallengeType
    chapter: int | None = None
    target: int = 1
    why: str | None = None


def from_ai(
    content: Any, cands: list[Candidate], fallback: list[dict], has_cards: bool = False
) -> tuple[list[dict], str | None]:
    """Keep the valid AI challenges (known type, chapter in the list when needed, no duplicate
    type+chapter, flashcards only for a student who has cards), snap targets to the catalogue,
    and fill up to 3 from the rule plan."""
    raw = content.get("challenges") if isinstance(content, dict) else None
    message = content.get("message") if isinstance(content, dict) else None
    out: list[dict] = []
    seen: set[tuple[str, str | None]] = set()
    for item in raw if isinstance(raw, list) else []:
        try:
            ch = AIChallenge.model_validate(item)
        except ValidationError:
            continue
        c = cands[ch.chapter - 1] if ch.chapter and 1 <= ch.chapter <= len(cands) else None
        if ch.type in NEEDS_CHAPTER and c is None:
            continue
        if ch.type == "flashcards" and not has_cards:
            continue
        key = (ch.type, str(c.chapter_id) if c else None)
        if key in seen:
            continue
        seen.add(key)
        why = (ch.why or "").strip()[:160] or None
        out.append(challenge(ch.type, ch.target, c, why))
        if len(out) == COUNT:
            break
    for f in fallback:
        if len(out) == COUNT:
            break
        if (f["type"], f["chapter_id"]) not in seen:
            seen.add((f["type"], f["chapter_id"]))
            out.append(f)
    msg = message.strip()[:200] if isinstance(message, str) and message.strip() else None
    return out, msg


def advance(
    ch: dict, event: str, chapter_id: str | None, amount: int, score_pct: int | None
) -> bool:
    """Apply one learning event to one challenge. Returns True if it just got done."""
    if ch["done"] or ch["type"] != event:
        return False
    if ch["chapter_id"] and chapter_id != ch["chapter_id"]:
        return False
    if event == "quiz_score":
        ch["progress"] = max(ch["progress"], score_pct or 0)
    else:
        ch["progress"] = min(ch["target"], ch["progress"] + amount)
    ch["done"] = ch["progress"] >= ch["target"]
    return ch["done"]
