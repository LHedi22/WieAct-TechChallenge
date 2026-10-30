"""The single table mapping TaskKind → tier + official pattern (ARCHITECTURE.md §Model routing).
Features never pick a model name; max_tokens budgets follow docs/MODELS.md."""

from dataclasses import dataclass

from app.gateway.types import TaskKind, Tier


@dataclass(frozen=True)
class Route:
    tier: Tier
    pattern: str
    max_tokens: int


K = TaskKind

ROUTES: dict[TaskKind, Route] = {
    K.INTENT_LANG: Route("compact", "triage", 60),
    K.CHUNK_TAG: Route("compact", "batch", 400),
    K.QUIZ_GENERATE: Route("compact", "narrow-before-generating", 1400),
    K.QUIZ_GRADE_TAG: Route("compact", "extraction", 120),
    K.TUTOR_TURN: Route("compact", "escalation", 220),
    K.TUTOR_SUMMARY: Route("compact", "summary", 200),
    K.TUTOR_GUARD: Route("compact", "guard", 160),
    K.NOTES_WRITE: Route("mid", "plan-once", 700),
    K.MAP_WRITE: Route("compact", "execute-compact", 400),  # from the mid notes (DECISIONS)
    K.AUDIO_SCRIPT: Route("mid", "narrow-before-generating", 700),
    K.FLASHCARDS: Route("compact", "execute-compact", 600),
    K.DAILY_PLAN: Route("mid", "plan-once", 400),
    K.CHALLENGE_ITEMS: Route("compact", "execute-compact", 400),
    K.WISDOM_TIP: Route("mid", "generate-once", 160),
    K.TEACHBACK_GRADE: Route("compact", "draft-then-revise", 300),
    K.MODERATE_POST: Route("compact", "classification", 40),
    K.TRANSLATE_SHORT: Route("compact", "rewriting", 200),
    K.PLACEMENT_QUIZ: Route("compact", "narrow-before-generating", 1100),
    K.JSON_REPAIR: Route("compact", "repair", 700),
    K.DEMO_SUMMARY: Route("mid", "narrow-before-generating", 300),
}


def route_for(kind: TaskKind) -> Route:
    return ROUTES[kind]
