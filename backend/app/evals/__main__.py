"""Prompt evals: generate questions from the seeded course and save them for review.

    uv run python -m app.evals quiz --langs en,fr,ar --n 20        # mock / local / cloud (in slot)
    uv run python -m app.evals quiz --world OLIVE-7Q2 --fresh      # bypass the cache

Writes backend/tests/evals/quiz/outputs/<provider>-<lang>.json with every question plus automatic
checks (structure, 4 distinct options, answer in range, script matches the language, the concept
appears in the excerpts, the hint does not give away the answer). Correctness is then reviewed by
a person or the `prompt-evaluator` agent; record the verdicts for the report (BUILD_PLAN M4)."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

OUT = Path(__file__).resolve().parents[2] / "tests" / "evals" / "quiz" / "outputs"
ARABIC = re.compile(r"[؀-ۿ]")
FRENCH = re.compile(r"\b(le|la|les|des|est|une|quelle|quel|pour|que)\b", re.IGNORECASE)
WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)


def check(q: dict[str, Any], lang: str, context: str) -> dict[str, bool]:
    from app.features.quiz.pool import Question

    try:
        Question.model_validate(q)
        valid = True
    except Exception:  # noqa: BLE001 - any validation error counts as invalid
        valid = False
    options = q.get("options") or []
    answer = q.get("answer_index")
    text = " ".join([str(q.get("question", "")), *map(str, options)])
    if lang.startswith("ar"):
        script = bool(ARABIC.search(text))
    elif lang == "fr":
        script = bool(FRENCH.search(text)) and not ARABIC.search(text)
    else:
        script = not ARABIC.search(text) and not FRENCH.search(str(q.get("question", "")))
    concept_words = WORD.findall(str(q.get("concept", "")).lower())
    grounded = bool(concept_words) and any(w in context.lower() for w in concept_words)
    right = options[answer] if isinstance(answer, int) and 0 <= answer < len(options) else ""
    hint = str(q.get("hint", ""))
    return {
        "valid": valid,
        "four_distinct_options": len({str(o).strip().lower() for o in options}) == 4,
        "answer_in_range": isinstance(answer, int) and 0 <= answer <= 3,
        "language_script": script,
        "concept_in_context": grounded,
        "hint_hides_answer": bool(hint) and (not right or right.lower() not in hint.lower()),
    }


async def quiz_eval(langs: list[str], n: int, world_code: str, fresh: bool, out: Path) -> int:
    from app import gateway, prompts
    from app.core import db
    from app.core.config import get_settings
    from app.features.quiz.pool import CONTEXT_CHUNKS, pick_context
    from app.gateway import Task, TaskKind
    from app.models import Chapter, Chunk, Course, World

    sm = db.get_sessionmaker()
    async with sm() as s:
        world = await s.scalar(select(World).where(World.join_code == world_code))
        if world is None:
            print(f"World {world_code} not found: run `uv run python -m app.seed --run` first")
            return 1
        rows = (
            await s.execute(
                select(Chapter, Course)
                .join(Course, Course.id == Chapter.course_id)
                .where(Course.world_id == world.id)
                .order_by(Course.name, Chapter.idx)
            )
        ).all()
        chunks = {
            ch.id: list(await s.scalars(select(Chunk).where(Chunk.chapter_id == ch.id)))
            for ch, _ in rows
        }
    chapters = [(ch, co) for ch, co in rows if chunks[ch.id]]
    if not chapters:
        print("No indexed chapters in the world yet")
        return 1
    stamp = str(int(time.time())) if fresh else "eval"
    await asyncio.to_thread(out.mkdir, parents=True, exist_ok=True)
    provider = get_settings().llm.provider
    for lang in langs:
        questions: list[dict[str, Any]] = []
        calls = 0
        while len(questions) < n and calls < max(2, n // 5):
            chapter, course = chapters[calls % len(chapters)]
            picked = pick_context(chunks[chapter.id], CONTEXT_CHUNKS, offset=calls)
            context = "\n\n".join(f"[{c.page_ref}] {c.text}" for c in picked)
            version, messages = prompts.render(
                "quiz_generate",
                count=10,
                level="intermediate",
                language=lang,
                course=course.name,
                chapter=chapter.title,
                context=context,
            )
            task = Task(
                kind=TaskKind.QUIZ_GENERATE,
                lane="background",
                messages=messages,
                language=lang,
                cache_key=f"{stamp}:{chapter.id}:{lang}:{calls}",
                prompt_version=version,
            )
            while True:  # the platform's quota: wait the stated delay, then continue
                try:
                    result = await gateway.run(task)
                    break
                except gateway.Defer as d:
                    print(f"  {d.reason}: waiting {d.delay_s:.0f}s")
                    await asyncio.sleep(d.delay_s)
            calls += 1
            raw = result.content.get("questions", []) if isinstance(result.content, dict) else []
            for q in raw if isinstance(raw, list) else []:
                if len(questions) < n:
                    questions.append(
                        {
                            "chapter": chapter.title,
                            "question": q,
                            "checks": check(q, lang, context),
                            "review": {"correct": None, "notes": ""},  # filled by the reviewer
                        }
                    )
        totals = {
            k: sum(item["checks"][k] for item in questions)
            for k in (questions[0]["checks"] if questions else {})
        }
        report = {
            "provider": provider,
            "model": result.model,
            "prompt": f"quiz_generate v{version}",
            "language": lang,
            "generated_at": datetime.now(UTC).isoformat(),
            "calls": calls,
            "count": len(questions),
            "checks_passed": totals,
            "questions": questions,
        }
        path = out / f"{provider}-{lang}.json"
        data = json.dumps(report, ensure_ascii=False, indent=2)
        await asyncio.to_thread(path.write_text, data, encoding="utf-8")
        summary = ", ".join(f"{k} {v}/{len(questions)}" for k, v in totals.items())
        print(f"{lang}: {len(questions)} questions in {calls} calls → {path.name} ({summary})")
    return 0


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(prog="python -m app.evals")
    p.add_argument("task", choices=["quiz"])
    p.add_argument("--langs", default="en,fr,ar")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--world", default="OLIVE-7Q2")
    p.add_argument("--fresh", action="store_true", help="new generations (skip the cache)")
    args = p.parse_args(argv)
    langs = [x.strip() for x in args.langs.split(",") if x.strip()]
    return asyncio.run(quiz_eval(langs, args.n, args.world, args.fresh, OUT))


if __name__ == "__main__":
    raise SystemExit(main())
