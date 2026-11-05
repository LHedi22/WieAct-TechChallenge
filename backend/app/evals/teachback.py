"""Teach-Back grading eval (audit N-1, N-2): the graded set in teachback_set.json (weak, acceptable,
strong, off-topic and injected answers to the same concept in en, fr, ar, ar-TN), graded through
the real path (arena.service.grade: rubric, evidence checks, review routing) on whatever provider
is active. No coins or points move: it calls the grader, not the API.

    uv run python -m app.evals teachback [--langs en,fr,ar,ar-TN] [--cloud]   # cloud: in slot

Outcome per item: flag, score (the server's total), finalised (False = held for a mid review that
did not happen), reviewed_by_mid. `checks()` turns the outcomes into pass/fail lines."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KINDS = ("weak", "acceptable", "strong", "off_topic", "injected")
SET = Path(__file__).with_name("teachback_set.json")
BAND_WIDTH = 20  # the same answer may move by at most 2 rubric levels across languages
REWARD = 70  # economy.PEER_ANSWER_THRESHOLD: an injected answer must never reach it finalised


def load_set() -> list[dict[str, Any]]:
    return json.loads(SET.read_text(encoding="utf-8"))["items"]


def concept() -> str:
    return json.loads(SET.read_text(encoding="utf-8"))["concept"]


def _ok(o: dict[str, Any]) -> bool:
    return o.get("flag") == "ok" and o.get("score") is not None


def checks(outcomes: list[dict[str, Any]]) -> dict[str, bool]:
    by = {(o["kind"], o["lang"]): o for o in outcomes}
    langs = sorted({o["lang"] for o in outcomes})
    graded = [o for o in outcomes if o["kind"] in ("weak", "acceptable", "strong") and _ok(o)]

    def ranks(lang: str) -> bool:
        w, a, s = (by.get((k, lang)) for k in ("weak", "acceptable", "strong"))
        if not all(o and _ok(o) for o in (w, a, s)):
            return False
        return w["score"] < a["score"] < s["score"]

    def same_band(kind: str) -> bool:
        scores = [by[(kind, lang)]["score"] for lang in langs if _ok(by.get((kind, lang)) or {})]
        return len(scores) == len(langs) and max(scores) - min(scores) <= BAND_WIDTH

    def nothing_for(o: dict[str, Any]) -> bool:
        return o.get("flag") != "ok" or (o.get("score") or 0) <= 20

    def not_rewarded(o: dict[str, Any]) -> bool:
        return o.get("flag") != "ok" or not o.get("finalised") or (o.get("score") or 0) < REWARD

    return {
        "scores_vary": len({o["score"] for o in graded}) >= 3,
        "ranks_weak_acceptable_strong": all(ranks(lang) for lang in langs),
        "same_answer_same_band_across_languages": all(
            same_band(k) for k in ("weak", "acceptable", "strong")
        ),
        "off_topic_gets_nothing": all(nothing_for(o) for o in outcomes if o["kind"] == "off_topic"),
        "injection_not_rewarded": all(not_rewarded(o) for o in outcomes if o["kind"] == "injected"),
    }


OUT = Path(__file__).resolve().parents[2] / "tests" / "evals" / "teachback" / "outputs"


async def run(langs: list[str], world_code: str, course_name: str, cloud: bool) -> int:
    """Grade every item of the set in `langs` through arena.service.grade() and save the outcomes
    and checks. Mid reviews that couldn't run (busy, budget) show as finalised=False."""
    import asyncio
    import time
    import uuid
    from datetime import UTC, datetime

    from sqlalchemy import func, select

    from app import gateway
    from app.core.config import get_settings
    from app.core.db import get_sessionmaker
    from app.features.arena import service
    from app.jobs.registry import JobContext
    from app.models import AICallLog, Chapter, Course, World

    provider = get_settings().llm.provider
    if provider == "cloud" and not cloud:
        print("The provider is cloud; every call counts on our key. Add --cloud.")
        return 2
    async with get_sessionmaker()() as s:
        world = await s.scalar(select(World).where(World.join_code == world_code))
        if world is None:
            print(f"World {world_code} not found: run `uv run python -m app.seed --run` first")
            return 1
        course = await s.scalar(
            select(Course).where(Course.world_id == world.id, Course.name == course_name)
        )
        chapter = await s.scalar(
            select(Chapter).where(Chapter.course_id == course.id).order_by(Chapter.idx)
        )
        first_log = await s.scalar(select(func.max(AICallLog.id))) or 0

    async def no_stage(_stage: str) -> None:
        return None

    outcomes: list[dict[str, Any]] = []
    items = [i for i in load_set() if i["lang"] in langs]
    started = time.monotonic()
    for item in items:
        ctx = JobContext(uuid.uuid4(), "EVAL", "interactive", {}, no_stage)
        try:
            for attempt in range(6):  # the quota or a busy model: wait the stated delay
                try:
                    g = await service.grade(
                        ctx,
                        mode="solo",
                        world_id=world.id,
                        chapter=chapter,
                        course=course,
                        prompt=concept(),
                        text=item["text"],
                        language=item["lang"],
                        user_id=None,
                    )
                    break
                except gateway.Defer as d:
                    if attempt == 5:
                        raise
                    print(f"  {d.reason}: waiting {d.delay_s:.0f}s")
                    await asyncio.sleep(d.delay_s)
            out = {
                "flag": g.grade.flag,
                "score": g.grade.score if g.grade.flag == "ok" else None,
                "finalised": not g.pending,
                "reviewed_by_mid": g.reviewed,
                "review_reasons": g.reasons,
                "confidence": g.grade.confidence,
                "criteria": {k: v.model_dump() for k, v in g.grade.criteria.items()},
                "quick_mode": ctx.quick_mode,
            }
        except gateway.GatewayError as e:
            reason = getattr(e, "reason", "") or str(e)
            out = {
                "flag": None,
                "score": None,
                "finalised": False,
                "error": f"{type(e).__name__}: {reason}",
            }
        outcomes.append({**item, **out})
        print(
            f"  {item['lang']:5} {item['kind']:10} → {out.get('flag')} {out.get('score')} "
            f"{'final' if out.get('finalised') else 'pending'} {out.get('review_reasons', '')}"
        )
    async with get_sessionmaker()() as s:
        rows = (
            await s.execute(
                select(AICallLog.model_tier, func.count())
                .where(AICallLog.id > first_log, AICallLog.task_kind == "TEACHBACK_GRADE")
                .group_by(AICallLog.model_tier)
            )
        ).all()
    result = checks(outcomes)
    report = {
        "provider": provider,
        "generated_at": datetime.now(UTC).isoformat(),
        "seconds": round(time.monotonic() - started),
        "calls": dict(rows),
        "checks": result,
        "outcomes": outcomes,
    }
    await asyncio.to_thread(OUT.mkdir, parents=True, exist_ok=True)
    path = OUT / f"{provider}-{int(time.time())}.json"
    data = json.dumps(report, ensure_ascii=False, indent=2)
    await asyncio.to_thread(path.write_text, data, encoding="utf-8")
    print(
        f"calls {dict(rows)} · "
        + " · ".join(f"{k} {'PASS' if v else 'FAIL'}" for k, v in result.items())
    )
    print(f"→ {path}")
    return 0 if all(result.values()) else 1
