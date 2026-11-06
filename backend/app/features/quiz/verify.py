"""Answer-key verification (audit N-3, draft-then-revise): before a compact-written quiz is
published, ONE mid call solves every question without seeing the key, hint or explanation. An
item survives only when the solver is sure and picks the keyed option.

Verification unavailable (mid busy, quota, offline) → `check()` returns None and the caller
decides: a student's quiz is published with `verified: false` on each item (labelled in the UI
and never handed to classmates), background work waits for mid instead."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app import gateway, prompts
from app.gateway import Task, TaskKind
from app.jobs.registry import JobContext


def _block(questions: list[dict[str, Any]]) -> str:
    lines = []
    for n, q in enumerate(questions, 1):
        lines.append(f"{n}. {q['question']}")
        lines += [f"   {k}) {o}" for k, o in enumerate(q["options"], 1)]
    return "\n".join(lines)


def render(
    questions: list[dict[str, Any]], *, context: str, course: str, chapter: str, language: str
) -> tuple[str, list[dict[str, str]]]:
    return prompts.render(
        "quiz_verify",
        questions=_block(questions),
        context=context,
        course=course,
        chapter=chapter,
        language=language,
    )


def verdicts(content: Any, questions: list[dict[str, Any]]) -> list[bool] | None:
    """Per question: the solver is sure and its answer is the key. None = an unusable reply."""
    raw = content.get("answers") if isinstance(content, dict) else None
    if not isinstance(raw, list):
        return None
    by_n: dict[int, dict[str, Any]] = {}
    for i, a in enumerate(raw, 1):
        if isinstance(a, dict):
            try:
                by_n[int(a.get("n", i))] = a
            except (TypeError, ValueError):
                continue
    out = []
    for n, q in enumerate(questions, 1):
        a = by_n.get(n) or {}
        try:
            picked = int(a["answer"]) - 1 if a.get("answer") is not None else None
        except (TypeError, ValueError):
            picked = None
        out.append(bool(a.get("sure")) and picked is not None and picked == q["answer_index"])
    return out


def keep_verified(questions: list[dict[str, Any]], ok: list[bool]) -> list[dict[str, Any]]:
    return [q | {"verified": True} for q, good in zip(questions, ok, strict=True) if good]


def mark_unverified(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [q | {"verified": False} for q in questions]


async def check(
    ctx: JobContext,
    questions: list[dict[str, Any]],
    *,
    context: str,
    course: str,
    chapter: str,
    language: str,
    lane: str,
) -> list[bool] | None:
    """One mid call (never a compact fallback: compact wrote the keys). None when it can't run."""
    version, messages = render(
        questions, context=context, course=course, chapter=chapter, language=language
    )
    digest = hashlib.sha256(
        json.dumps([questions, context], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:32]
    try:
        result = ctx.note(
            await gateway.run(
                Task(
                    kind=TaskKind.QUIZ_VERIFY,
                    lane=lane,
                    messages=messages,
                    language=language,
                    tier="mid",
                    allow_fallback=False,
                    cache_key=f"quiz-verify:{digest}",
                    prompt_version=version,
                )
            )
        )
    except gateway.GatewayError:
        return None
    return verdicts(result.content, questions)
