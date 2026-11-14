"""The single table mapping TaskKind → tier + official pattern (ARCHITECTURE.md §Model routing).
Features never pick a model name; max_tokens budgets follow docs/MODELS.md.

Logged patterns start with an official name (PLATFORM.md), the error contract's `fallback`, or
`none`; a step that is no orchestration pattern keeps its internal name as a sub-label after a
colon, e.g. `none:guard` (audit OPT-08, DECISIONS 2026-11-14)."""

from dataclasses import dataclass

from app.gateway.types import TaskKind, Tier


@dataclass(frozen=True)
class Route:
    tier: Tier
    pattern: str
    max_tokens: int


OFFICIAL = (
    "escalation",
    "draft-then-revise",
    "plan-once",
    "execute-compact",
    "narrow-before-generating",
    "fallback",
    "none",
)
# Labels logged before OPT-08 → their official name (old ai_call_log rows in the stats).
LEGACY = {"forced-fallback": "fallback"}


def official(pattern: str) -> str:
    """The official name a logged pattern counts under."""
    head = pattern.split(":", 1)[0]
    if head in OFFICIAL:
        return head
    return LEGACY.get(pattern, "none")


K = TaskKind

ROUTES: dict[TaskKind, Route] = {
    K.INTENT_LANG: Route("compact", "none:triage", 60),
    K.CHUNK_TAG: Route("compact", "none:batch", 800),  # 8 chunks ≈ 500 tokens of JSON (probe 7 Nov)
    K.QUIZ_GENERATE: Route("compact", "narrow-before-generating", 1700),  # 12 Q (OPT-14)
    K.QUIZ_GRADE_TAG: Route("compact", "none:extraction", 120),
    K.QUIZ_VERIFY: Route("mid", "draft-then-revise", 800),  # 12 keys + a step each (N-3, OPT-14)
    K.TUTOR_TURN: Route("compact", "escalation", 220),
    K.TUTOR_SUMMARY: Route("compact", "none:summary", 200),
    K.TUTOR_GUARD: Route("compact", "none:guard", 160),
    K.NOTES_WRITE: Route("mid", "plan-once", 700),
    K.MAP_WRITE: Route("compact", "execute-compact", 400),  # from the mid notes (DECISIONS)
    K.AUDIO_SCRIPT: Route("mid", "narrow-before-generating", 700),
    K.FLASHCARDS: Route("compact", "execute-compact", 600),
    K.DAILY_PLAN: Route("compact", "escalation", 400),  # mid for recorded weak spots (OPT-09)
    K.CHALLENGE_ITEMS: Route("compact", "execute-compact", 400),
    K.WISDOM_TIP: Route("mid", "none:generate-once", 160),
    K.TEACHBACK_GRADE: Route("compact", "draft-then-revise", 450),
    K.MODERATE_POST: Route("compact", "none:classification", 40),
    K.TRANSLATE_SHORT: Route("compact", "none:rewriting", 200),
    K.PLACEMENT_QUIZ: Route("compact", "narrow-before-generating", 1100),
    K.JSON_REPAIR: Route("compact", "none:repair", 700),
    K.DEMO_SUMMARY: Route("mid", "narrow-before-generating", 300),
}


def route_for(kind: TaskKind) -> Route:
    return ROUTES[kind]
