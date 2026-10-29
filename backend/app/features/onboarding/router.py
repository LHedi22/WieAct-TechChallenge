"""Onboarding: the learning-style test (scored here, no AI) and the profile (level, style, goals,
avatar — nothing identifying)."""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.core import economy
from app.models import Profile

router = APIRouter(prefix="/api", tags=["onboarding"])

Style = Literal["visual", "practice", "listening", "teaching"]
STYLES: tuple[Style, ...] = ("visual", "practice", "listening", "teaching")
# Where each style is pointed first (every building stays open to everyone).
SUGGEST = {
    "visual": "study_studio",
    "practice": "quiz_hall",
    "listening": "audio_studio",
    "teaching": "teachback_arena",
}
SKINS = ("s1", "s2", "s3", "s4", "s5")
OUTFITS = ("o1", "o2", "o3", "o4", "o5")
Language = Literal["en", "fr", "ar", "ar-TN"]


def style_mix(answers: list[Style]) -> dict[str, int]:
    """Percentages from the scenario answers: 1 point per style to start (nobody is 0% anything),
    +1 per answer; rounded with the largest-remainder method so they always sum to 100."""
    counts = {s: 1 + answers.count(s) for s in STYLES}
    total = sum(counts.values())
    raw = {s: 100 * c / total for s, c in counts.items()}
    pct = {s: int(v) for s, v in raw.items()}
    by_remainder = sorted(STYLES, key=lambda s: (raw[s] - pct[s], raw[s]), reverse=True)
    for s in by_remainder[: 100 - sum(pct.values())]:  # ties go to the bigger share
        pct[s] += 1
    return pct


def suggestions(mix: dict[str, int]) -> list[str]:
    ranked = sorted(STYLES, key=lambda s: (-mix[s], STYLES.index(s)))
    return [SUGGEST[s] for s in ranked[:2]]


class StyleIn(BaseModel):
    answers: list[Style] = Field(min_length=1, max_length=8)


class StyleOut(BaseModel):
    mix: dict[str, int]
    top: list[Style]
    suggested_buildings: list[str]


class Avatar(BaseModel):
    skin: str
    outfit: str
    extra: str | None = None


class ProfileIn(BaseModel):
    university: str | None = Field(None, max_length=80)
    field: str | None = Field(None, max_length=80)
    year: int | None = Field(None, ge=1, le=8)
    languages: list[Language] | None = None
    daily_minutes: int | None = Field(None, ge=5, le=600)
    reminder_time: time | None = None
    goal: Literal["pass", "grade", "deep"] | None = None
    leaderboard_opt_in: bool | None = None
    avatar: Avatar | None = None
    finish: bool = False  # sets onboarded_at (also when the student skips)


class ProfileOut(BaseModel):
    university: str | None
    field: str | None
    year: int | None
    mix: dict[str, int]
    languages: list[str]
    daily_minutes: int | None
    reminder_time: time | None
    goal: str | None
    leaderboard_opt_in: bool
    avatar: dict | None
    onboarded: bool


async def _profile(s, user_id) -> Profile:
    profile = await s.get(Profile, user_id)
    if profile is None:
        profile = Profile(
            user_id=user_id,
            style_visual=25,
            style_practice=25,
            style_listening=25,
            style_teaching=25,
            languages=[],
            leaderboard_opt_in=True,
        )
        s.add(profile)
        await s.flush()
    return profile


def _out(p: Profile) -> ProfileOut:
    return ProfileOut(
        university=p.university,
        field=p.field,
        year=p.year,
        mix={
            "visual": p.style_visual,
            "practice": p.style_practice,
            "listening": p.style_listening,
            "teaching": p.style_teaching,
        },
        languages=list(p.languages or []),
        daily_minutes=p.daily_minutes,
        reminder_time=p.reminder_time,
        goal=p.goal,
        leaderboard_opt_in=p.leaderboard_opt_in,
        avatar=p.avatar,
        onboarded=p.onboarded_at is not None,
    )


@router.post("/onboarding/style", response_model=StyleOut)
async def score_style(body: StyleIn, s: Session, user: CurrentUser) -> StyleOut:
    mix = style_mix(body.answers)
    profile = await _profile(s, user.id)
    profile.style_visual = mix["visual"]
    profile.style_practice = mix["practice"]
    profile.style_listening = mix["listening"]
    profile.style_teaching = mix["teaching"]
    await s.commit()
    top = sorted(STYLES, key=lambda st: (-mix[st], STYLES.index(st)))[:2]
    return StyleOut(mix=mix, top=list(top), suggested_buildings=suggestions(mix))


@router.get("/profile", response_model=ProfileOut)
async def get_profile(s: Session, user: CurrentUser) -> ProfileOut:
    profile = await _profile(s, user.id)
    await s.commit()
    return _out(profile)


@router.put("/profile", response_model=ProfileOut)
async def put_profile(body: ProfileIn, s: Session, user: CurrentUser) -> ProfileOut:
    profile = await _profile(s, user.id)
    if body.avatar is not None:
        a = body.avatar
        if a.skin not in SKINS or a.outfit not in OUTFITS:
            raise HTTPException(400, "errors.avatar_invalid")
        if a.extra is not None:
            if a.extra not in economy.COSMETICS:
                raise HTTPException(400, "errors.avatar_invalid")
            if economy.COSMETICS[a.extra] > 0:  # points arrive with M5; nothing is unlocked yet
                raise HTTPException(403, "errors.cosmetic_locked")
        profile.avatar = a.model_dump()
    for name in (
        "university",
        "field",
        "year",
        "languages",
        "daily_minutes",
        "reminder_time",
        "goal",
        "leaderboard_opt_in",
    ):
        value = getattr(body, name)
        if value is not None:
            setattr(profile, name, value.strip() if isinstance(value, str) else value)
    if body.finish and profile.onboarded_at is None:
        profile.onboarded_at = datetime.now(UTC)
    await s.commit()
    return _out(profile)
