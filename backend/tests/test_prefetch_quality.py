# ruff: noqa: F811  (pytest fixtures imported from other test modules)
"""Prefetch step 6: background quality checks (PREFETCH_QUALITY_PASS, off by default) on
prefetched content still in the background lane: a mid review of the notes (draft-then-revise),
a compact check of the cards against the notes, and one placement regeneration when too few
answer keys survive. Each is counted in the mid caps and skipped once they are reached."""

import uuid
from collections import Counter

import mock_llm.app as mock_app
from sqlalchemy import func, select

from app.features.studio import pack
from app.jobs import prefetch
from app.models import AICallLog, Flashcard, PlacementSet, StudyAsset
from tests.test_prefetch import (
    KID,
    plan,
    plan_world,
    prefetch_on,  # noqa: F401  (autouse fixture)
    roomy_mock,  # noqa: F401  (autouse fixture)
    set_env,
    settle,
    two_chapters,
)
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import api, pptx  # noqa: F401  (fixtures)


async def calls(sm) -> Counter:
    async with sm() as s:
        rows = await s.scalars(select(AICallLog.task_kind).where(AICallLog.cache_hit.is_(False)))
        return Counter(rows)


async def notes_of(sm, chapter: str, level: str = "advanced") -> StudyAsset:
    async with sm() as s:
        return await s.scalar(
            select(StudyAsset).where(
                StudyAsset.chapter_id == uuid.UUID(chapter),
                StudyAsset.level == level,
                StudyAsset.kind == "notes",
            )
        )


async def test_off_by_default_no_extra_calls(api, sm, pptx, monkeypatch):
    _, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    await plan(sm, ch1)
    await settle(sm)
    made = await calls(sm)
    assert made["NOTES_REVIEW"] == made["CARDS_CHECK"] == 0
    assert "review" not in (await notes_of(sm, ch2)).content


async def test_it_reviews_prefetched_notes_and_drops_unsupported_cards(api, sm, pptx, monkeypatch):
    _, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    set_env(monkeypatch, PREFETCH_QUALITY_PASS="true")
    review = {
        "ok": False,
        "fixes": [{"section": 1, "points": ["Fixed point."]}],
        "missing": ["Trees"],
    }
    monkeypatch.setitem(mock_app.GENERATORS, "NOTES_REVIEW", lambda *a, **k: review)
    monkeypatch.setitem(mock_app.GENERATORS, "CARDS_CHECK", lambda *a, **k: {"unsupported": [1]})
    await plan(sm, ch1)
    await settle(sm)
    made = await calls(sm)
    assert (made["NOTES_REVIEW"], made["CARDS_CHECK"]) == (1, 1)
    async with sm() as s:
        tiers = dict(
            (
                await s.execute(
                    select(AICallLog.task_kind, AICallLog.model_tier).where(
                        AICallLog.task_kind.in_(("NOTES_REVIEW", "CARDS_CHECK"))
                    )
                )
            ).all()
        )
    assert tiers == {"NOTES_REVIEW": "mid", "CARDS_CHECK": "compact"}
    notes = (await notes_of(sm, ch2)).content
    assert notes["sections"][0]["points"] == ["Fixed point."]
    assert notes["review"] == {"fixed": 1, "missing": ["Trees"]}
    async with sm() as s:
        cards = await s.scalar(
            select(func.count())
            .select_from(Flashcard)
            .where(Flashcard.chapter_id == uuid.UUID(ch2))
        )
    assert cards == pack.CARD_COUNT - 1  # card 1 dropped


def test_an_unusable_review_keeps_the_notes():
    notes = {"title": "T", "sections": [{"heading": "H", "points": ["a", "b"], "refs": []}]}
    for content in (
        "not json",
        {"fixes": [{"section": 0, "points": ["x"]}]},  # sections count from 1
        {"fixes": [{"section": 2, "points": ["x"]}]},  # no such section
        {"fixes": [{"section": 1, "points": "x"}]},
        {"fixes": [{"section": 1, "points": ["x" * 301]}]},
        {"fixes": [{"section": "1", "points": ["x"]}]},
    ):
        out = pack.apply_review(notes, content)
        assert out["sections"] == notes["sections"] and out["review"]["fixed"] == 0, content


async def test_a_promoted_pack_skips_the_checks(api, sm, pptx, monkeypatch):
    _, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    set_env(monkeypatch, PREFETCH_QUALITY_PASS="true")
    await plan(sm, ch1)
    await api.post(f"/api/studio/{ch2}/generate", json={"level": "advanced"}, headers=KID)
    await settle(sm)
    made = await calls(sm)
    assert made["NOTES_WRITE"] >= 1 and made["NOTES_REVIEW"] == made["CARDS_CHECK"] == 0


async def test_the_review_counts_in_the_cap_and_stops_at_it(api, sm, pptx, monkeypatch):
    _, ch1, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    set_env(monkeypatch, PREFETCH_QUALITY_PASS="true", PREFETCH_MAX_MID_PER_WORLD_PER_DAY=3)
    queued = await plan(sm, ch1)  # quiz 1 + pack 2 (notes + review) = 3: no room for audio
    assert len(queued) == 2
    set_env(monkeypatch, PREFETCH_MAX_MID_PER_WORLD_PER_DAY=1)  # spent meanwhile
    await settle(sm)
    made = await calls(sm)
    assert made["NOTES_WRITE"] == 1 and made["NOTES_REVIEW"] == 0


async def test_placement_regenerates_once_when_too_few_keys_survive(api, sm, pptx, monkeypatch):
    world, *_ = await two_chapters(api, sm, pptx, monkeypatch)
    set_env(monkeypatch, PREFETCH_QUALITY_PASS="true")
    real, seen = mock_app.GENERATORS["QUIZ_VERIFY"], []

    def unsure_first(user, lang, system=""):
        seen.append(1)
        out = real(user, lang, system)
        if len(seen) == 1:  # the first check confirms no key
            out = {**out, "answers": [{**a, "answer": None, "sure": False} for a in out["answers"]]}
        return out

    monkeypatch.setitem(mock_app.GENERATORS, "QUIZ_VERIFY", unsure_first)
    draft = mock_app.GENERATORS["PLACEMENT_QUIZ"]

    def redrafts(user, lang, system=""):  # a model writes new questions when told to
        out = draft(user, lang, system)
        if "FIRST DRAFT FAILED" in user:
            out = {**out, "questions": [{**q, "question": q["question"] + " (v2)"}
                                        for q in out["questions"]]}  # fmt: skip
        return out

    monkeypatch.setitem(mock_app.GENERATORS, "PLACEMENT_QUIZ", redrafts)
    set_env(monkeypatch, PREFETCH_MAX_MID_PER_WORLD_PER_DAY=1)
    assert len(await plan_world(sm, world)) == 1  # placement first: the only job that fits
    set_env(monkeypatch, PREFETCH_MAX_MID_PER_WORLD_PER_DAY=10)  # room for the regeneration
    await settle(sm)
    made = await calls(sm)
    assert (made["PLACEMENT_QUIZ"], len(seen)) == (2, 2)
    async with sm() as s:  # the regeneration is a revision, never the same request again
        hashes = (
            await s.scalars(
                select(AICallLog.request_hash).where(AICallLog.task_kind == "PLACEMENT_QUIZ")
            )
        ).all()
    assert len(set(hashes)) == 2
    async with sm() as s:
        assert await s.scalar(select(PlacementSet.id)) is not None


async def test_the_planner_counts_two_mid_per_pack_with_the_pass(monkeypatch):
    assert prefetch.expected_mid("STUDY_PACK") == 1
    set_env(monkeypatch, PREFETCH_QUALITY_PASS="true")
    assert prefetch.expected_mid("STUDY_PACK") == 2 and prefetch.expected_mid("QUIZ_POOL") == 1
