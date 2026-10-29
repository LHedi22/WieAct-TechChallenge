"""Socratic Tutor: never gives the final answer.

Each AI step is a TUTOR job (interactive lane):
- plan  — ONE compact call: goal + 3 ideas to discover + the opening question (costs a
          tutor_session)
- turn  — narrow (search the student's words in the chapter, k=4) → compact TUTOR_TURN, or **mid**
          after 2 "I'm stuck" signals / when the model flags the topic complex (escalation); the
          gateway falls back to compact (quick mode) if mid is saturated
- guard — a cheap check on every reply; only replies that state an answer get ONE compact
          TUTOR_GUARD rewrite into a guiding question
- summary — compact TUTOR_SUMMARY at the end (cached by session)"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import gateway, prompts
from app.core import db, economy
from app.gateway import Task, TaskKind
from app.jobs.registry import JobContext, job
from app.jobs.service import create_job
from app.models import Chapter, Course, Job, Profile, TutorSession, User
from app.rag.search import search

KIND = "TUTOR"
MAX_HINTS = 3
STUCK_TO_ESCALATE = 2
HISTORY_TURNS = 6
CONTEXT_K = 4
Action = Literal["message", "hint", "another_way", "stuck"]

# Phrases that state an answer instead of asking (en / fr / ar / Darija). Conservative on purpose:
# a false positive only costs one compact rewrite.
LEAK = re.compile(
    r"(the (final )?answer is|the result is|the solution is|equals? \$?[-\d]|"
    r"la (bonne )?réponse est|le résultat est|la solution est|"
    r"الجواب هو|الإجابة هي|النتيجة هي|الحل هو|الجواب متاعو)",
    re.IGNORECASE,
)

ACTION_NOTES = {
    "message": "",
    "hint": "The student asked for a hint: give ONE small hint (not the answer), then a question.",
    "another_way": "The student asked for another explanation: use a different angle (an analogy, "
    "a concrete example, or a picture described in words), then a question.",
    "stuck": "The student is stuck: break the problem into a smaller first step and ask about it.",
}
# Last resort if even the rewrite states the answer: a safe guiding question, never the answer.
FALLBACK_QUESTION = {
    "en": "Let's go one step at a time: what do you get if you try the very first step yourself?",
    "fr": "Allons-y pas à pas : qu'obtiens-tu si tu fais toi-même la toute première étape ?",
    "ar": "لنمضِ خطوة بخطوة: ماذا تجد إذا جرّبت الخطوة الأولى بنفسك؟",
    "ar-TN": "نمشيو خطوة بخطوة: شنوّة تلقى كان تجرّب الخطوة الأولى وحدك؟",
}
STYLE_NOTES = {
    "visual": "This student learns best from pictures: describe diagrams in words.",
    "practice": "This student learns best from examples: use a small concrete example.",
    "listening": "This student learns best from explanations: talk it through simply.",
    "teaching": "This student learns best by explaining: ask them to explain a step back to you.",
}


class Rejected(Exception):
    def __init__(self, key: str, status: int = 400) -> None:
        super().__init__(key)
        self.key = key
        self.status = status


class PlanReply(BaseModel):
    goal: str
    ideas: list[str] = Field(min_length=1)
    reply: str


class TurnReply(BaseModel):
    reply: str
    ideas_found: list[int] = Field(default_factory=list)
    complex: bool = False
    confidence: Literal["ok", "low"] = "ok"


def leaks_answer(reply: str) -> bool:
    """A reply that states an answer, or does not ask the student anything back."""
    text = reply.strip()
    return bool(LEAK.search(text)) or not text.rstrip(" .!*)»\"'").endswith(("?", "؟"))


def _style_note(profile: Profile | None) -> str:
    if profile is None:
        return ""
    mix = {
        "visual": profile.style_visual,
        "practice": profile.style_practice,
        "listening": profile.style_listening,
        "teaching": profile.style_teaching,
    }
    top = max(mix, key=lambda k: mix[k])
    return STYLE_NOTES[top] if mix[top] > 25 else ""


# --- API side ------------------------------------------------------------------------------------
async def _pending(s: AsyncSession, session: TutorSession) -> bool:
    if session.pending_job_id is None:
        return False
    j = await s.get(Job, session.pending_job_id)
    return j is not None and j.status in ("queued", "running")


async def start(s: AsyncSession, user: User, chapter: Chapter, level: str) -> TutorSession:
    course = await s.get(Course, chapter.course_id)
    session = TutorSession(
        user_id=user.id,
        world_id=course.world_id,
        course_id=course.id,
        chapter_id=chapter.id,
        level=level,
        language=user.ui_language,
        ideas=[],
        turns=[],
        hints_used=0,
        stuck_count=0,
        escalate_next=False,
        status="active",
    )
    s.add(session)
    await s.flush()
    j = await create_job(
        s,
        kind=KIND,
        lane="interactive",
        payload={"session_id": str(session.id), "mode": "plan"},
        user_id=user.id,
        world_id=course.world_id,
        cost=economy.COST["tutor_session"],
    )
    session.pending_job_id = j.id
    await s.commit()
    return session


async def turn(s: AsyncSession, session: TutorSession, text: str, action: Action) -> uuid.UUID:
    if session.status != "active":
        raise Rejected("errors.tutor_ended", 409)
    if await _pending(s, session):
        raise Rejected("errors.tutor_busy", 409)
    text = text.strip()
    if action == "message" and not text:
        raise Rejected("errors.tutor_empty")
    if action == "hint":
        if session.hints_used >= MAX_HINTS:
            raise Rejected("errors.tutor_no_hints")
        session.hints_used += 1
    if action == "stuck":
        session.stuck_count += 1
        if session.stuck_count >= STUCK_TO_ESCALATE:
            session.escalate_next = True
    session.turns = [
        *session.turns,
        {
            "role": "student",
            "text": text[:1500],
            "action": action,
            "at": datetime.now(UTC).isoformat(),
        },
    ]
    j = await create_job(
        s,
        kind=KIND,
        lane="interactive",
        payload={"session_id": str(session.id), "mode": "turn"},
        user_id=session.user_id,
        world_id=session.world_id,
    )
    session.pending_job_id = j.id
    await s.commit()
    return j.id


async def end(s: AsyncSession, session: TutorSession) -> uuid.UUID:
    if session.status != "active":
        raise Rejected("errors.tutor_ended", 409)
    if await _pending(s, session):
        raise Rejected("errors.tutor_busy", 409)
    j = await create_job(
        s,
        kind=KIND,
        lane="interactive",
        payload={"session_id": str(session.id), "mode": "summary"},
        user_id=session.user_id,
        world_id=session.world_id,
    )
    session.pending_job_id = j.id
    await s.commit()
    return j.id


# --- the job -------------------------------------------------------------------------------------
def _history(turns: list[dict[str, Any]], n: int = HISTORY_TURNS) -> str:
    lines = []
    for t in turns[-n:]:
        who = "Student" if t["role"] == "student" else "Tutor"
        lines.append(f"{who}: {t['text'] or '(' + t.get('action', '') + ')'}")
    return "\n".join(lines) or "(start)"


async def _context(session: TutorSession, chapter: Chapter, query: str) -> str:
    try:
        hits = await search(
            session.world_id, query, chapter_id=chapter.id, k=CONTEXT_K, lane="interactive"
        )
    except gateway.Defer:
        raise
    except gateway.GatewayError:
        hits = []
    return "\n\n".join(f"[{h.page_ref}] {h.text[:900]}" for h in hits) or "(no excerpt found)"


async def _save(session_id: uuid.UUID, **changes: Any) -> None:
    async with db.get_sessionmaker()() as s:
        row = await s.get(TutorSession, session_id)
        for k, v in changes.items():
            setattr(row, k, v)
        row.pending_job_id = None
        await s.commit()


def _parse(model: type[BaseModel], content: Any) -> BaseModel | None:
    try:
        return model.model_validate(content)
    except ValidationError:
        return None


@job(KIND, stages=("reading_chapter", "thinking", "checking_reply"))
async def tutor_step(ctx: JobContext) -> dict[str, Any]:
    session_id = uuid.UUID(ctx.payload["session_id"])
    mode = ctx.payload["mode"]
    async with db.get_sessionmaker()() as s:
        session = await s.get(TutorSession, session_id)
        chapter = await s.get(Chapter, session.chapter_id)
        course = await s.get(Course, session.course_id)
        profile = await s.get(Profile, session.user_id)
    lang = session.language
    await ctx.set_stage("reading_chapter")

    if mode == "summary":
        found = [i["text"] for i in session.ideas if i.get("found")]
        missing = [i["text"] for i in session.ideas if not i.get("found")]
        version, messages = prompts.render(
            "tutor_summary",
            language=lang,
            goal=session.goal or chapter.title,
            found="; ".join(found) or "-",
            missing="; ".join(missing) or "-",
            history=_history(session.turns, 12),
        )
        await ctx.set_stage("thinking")
        result = ctx.note(
            await gateway.run(
                Task(
                    kind=TaskKind.TUTOR_SUMMARY,
                    lane="interactive",
                    messages=messages,
                    language=lang,
                    cache_key=f"tutor-summary:{session_id}",
                    prompt_version=version,
                )
            )
        )
        content = result.content if isinstance(result.content, dict) else {}
        summary = {
            "summary": str(content.get("summary") or ""),
            "next_step": str(content.get("next_step") or ""),
            "ideas_found": found,
            "ideas_missing": missing,
        }
        await _save(session_id, summary=summary, status="ended", ended_at=datetime.now(UTC))
        return {"session_id": str(session_id), "mode": mode}

    style = _style_note(profile)
    if mode == "plan":
        context = await _context(session, chapter, f"{chapter.title} ({session.level})")
        version, messages = prompts.render(
            "tutor_plan",
            language=lang,
            level=session.level,
            style_note=style,
            course=course.name,
            chapter=chapter.title,
            context=context,
        )
        await ctx.set_stage("thinking")
        result = ctx.note(
            await gateway.run(
                Task(
                    kind=TaskKind.TUTOR_TURN,
                    lane="interactive",
                    messages=messages,
                    language=lang,
                    cache_key=None,  # personal conversation: never shared
                    prompt_version=version,
                )
            )
        )
        plan = _parse(PlanReply, result.content)
        if plan is None:
            raise gateway.BadOutput("tutor plan did not validate", refusal="bad_plan")
        reply = await _guarded(ctx, plan.reply, lang)
        await _save(
            session_id,
            goal=plan.goal[:300],
            ideas=[{"text": t[:160], "found": False} for t in plan.ideas[:3]],
            turns=[*session.turns, _tutor_turn(reply, result)],
        )
        return {"session_id": str(session_id), "mode": mode}

    # mode == "turn"
    last = next((t for t in reversed(session.turns) if t["role"] == "student"), None)
    action: Action = (last or {}).get("action", "message")
    message = (last or {}).get("text") or ""
    context = await _context(session, chapter, message or session.goal or chapter.title)
    ideas = "\n".join(
        f"{i}: {idea['text']} — {'found' if idea.get('found') else 'not yet'}"
        for i, idea in enumerate(session.ideas)
    )
    version, messages = prompts.render(
        "tutor_turn",
        language=lang,
        level=session.level,
        style_note=style,
        action_note=ACTION_NOTES[action],
        goal=session.goal or chapter.title,
        ideas=ideas or "-",
        context=context,
        history=_history(session.turns[:-1]),
        action=action,
        message=message or f"({action})",
    )
    escalate = session.escalate_next
    await ctx.set_stage("thinking")
    result = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.TUTOR_TURN,
                lane="interactive",
                messages=messages,
                language=lang,
                cache_key=None,
                tier="mid" if escalate else None,  # escalation: stuck twice / flagged complex
                prompt_version=version,
            )
        )
    )
    parsed = _parse(TurnReply, result.content)
    if parsed is None:
        raise gateway.BadOutput("tutor turn did not validate", refusal="bad_turn")
    reply = await _guarded(ctx, parsed.reply, lang)
    new_ideas = [
        {**idea, "found": idea.get("found") or i in parsed.ideas_found}
        for i, idea in enumerate(session.ideas)
    ]
    ran_mid = result.model_tier == "mid"
    await _save(
        session_id,
        ideas=new_ideas,
        turns=[*session.turns, _tutor_turn(reply, result, parsed.confidence)],
        # after a mid turn, go back to compact until the student is stuck again
        escalate_next=False if ran_mid else parsed.complex,
        stuck_count=0 if ran_mid else session.stuck_count,
    )
    return {"session_id": str(session_id), "mode": mode, "tier": result.model_tier}


def _tutor_turn(text: str, result: gateway.Result, confidence: str = "ok") -> dict[str, Any]:
    return {
        "role": "tutor",
        "text": text,
        "tier": result.model_tier,
        "quick_mode": result.quick_mode,
        "confidence": confidence,
        "at": datetime.now(UTC).isoformat(),
    }


async def _guarded(ctx: JobContext, reply: str, lang: str) -> str:
    """Hints before answers: a reply that states the answer becomes a question (one call)."""
    if not leaks_answer(reply):
        return reply
    await ctx.set_stage("checking_reply")
    version, messages = prompts.render("tutor_guard", language=lang, reply=reply)
    fixed = ctx.note(
        await gateway.run(
            Task(
                kind=TaskKind.TUTOR_GUARD,
                lane="interactive",
                messages=messages,
                language=lang,
                cache_key=None,
                prompt_version=version,
            )
        )
    )
    text = fixed.content.get("reply") if isinstance(fixed.content, dict) else None
    return (
        text
        if text and not LEAK.search(text)
        else FALLBACK_QUESTION.get(lang, FALLBACK_QUESTION["en"])
    )
