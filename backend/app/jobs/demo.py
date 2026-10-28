"""M1 demo job: a mid-size summary of a fixed public passage. Exercises the whole path (job →
worker → gateway → contract handling → loading stages) before any real feature exists."""

from __future__ import annotations

import asyncio
from typing import Any

from app import gateway, prompts
from app.gateway import Task, TaskKind
from app.jobs.registry import JobContext, job

KIND = "DEMO_SUMMARY"

PASSAGE = (
    "Chapter 1 - Limits. The limit of f(x) as x approaches a is the value f(x) gets close to when "
    "x gets close to a, whether or not f(a) is defined. If direct substitution gives 0/0, the form "
    "is indeterminate: simplify first (factor, cancel, or rationalise). Example: (x^2-4)/(x-2) = "
    "x+2 for x != 2, so the limit as x->2 is 4. One-sided limits must agree for the limit to exist."
)


@job(KIND, stages=("reading_chapter", "writing_summary"))
async def demo_summary(ctx: JobContext) -> dict[str, Any]:
    language = ctx.payload.get("language", "en")
    await ctx.set_stage("reading_chapter")
    await asyncio.sleep(0.3)  # stands in for retrieval (M2: vector search + compact filter)
    await ctx.set_stage("writing_summary")
    version, messages = prompts.render(
        "demo_summary", language=language, topic="Calculus I", text=PASSAGE
    )
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.DEMO_SUMMARY,
                lane=ctx.lane,
                messages=messages,
                language=language,
                cache_key=ctx.payload.get("cache_key"),
                prompt_version=version,
            )
        )
    )
    return {
        "summary": result.content,
        "model_tier": result.model_tier,
        "provider": result.provider,
        "cached": result.cached,
    }
