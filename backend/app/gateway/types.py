from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

Tier = Literal["compact", "mid"]
Lane = Literal["interactive", "background"]


class TaskKind(StrEnum):
    INTENT_LANG = "INTENT_LANG"
    CHUNK_TAG = "CHUNK_TAG"
    QUIZ_GENERATE = "QUIZ_GENERATE"
    QUIZ_GRADE_TAG = "QUIZ_GRADE_TAG"
    TUTOR_TURN = "TUTOR_TURN"
    TUTOR_SUMMARY = "TUTOR_SUMMARY"
    NOTES_WRITE = "NOTES_WRITE"
    MAP_WRITE = "MAP_WRITE"
    AUDIO_SCRIPT = "AUDIO_SCRIPT"
    FLASHCARDS = "FLASHCARDS"
    DAILY_PLAN = "DAILY_PLAN"
    CHALLENGE_ITEMS = "CHALLENGE_ITEMS"
    WISDOM_TIP = "WISDOM_TIP"
    TEACHBACK_GRADE = "TEACHBACK_GRADE"
    MODERATE_POST = "MODERATE_POST"
    TRANSLATE_SHORT = "TRANSLATE_SHORT"
    PLACEMENT_QUIZ = "PLACEMENT_QUIZ"
    JSON_REPAIR = "JSON_REPAIR"  # internal: one compact "fix this JSON" call
    DEMO_SUMMARY = "DEMO_SUMMARY"  # M1 demo job (mid, background-friendly)
    EMBED = "EMBED"  # embeddings endpoint (separately metered); logged as model_tier="embed"


class Task(BaseModel):
    kind: TaskKind
    lane: Lane
    messages: list[dict[str, Any]]
    language: str = "en"
    cache_key: str | None = None  # None = never cache (tutor turns, personal data)
    response_format: Literal["json", "text"] = "json"
    max_tokens: int | None = None  # default from the routing table
    allow_fallback: bool = True
    tier: Tier | None = None  # override the routed tier (e.g. tutor escalation to mid)
    prompt_version: str = "1"


class Result(BaseModel):
    content: Any
    model_tier: Tier
    model: str
    provider: str
    pattern: str
    quick_mode: bool = False  # fell back from mid to compact
    cached: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    notes: list[str] = Field(default_factory=list)  # e.g. "shrunk max_tokens to 1024"


class EmbedResult(BaseModel):
    vectors: list[list[float]]
    provider: str  # the profile whose collection these vectors belong in
    model: str
    cached: bool = False
    calls: int = 0
