"""Answer-key verifier eval (audit N-3): quiz_key_set.json holds items whose key is known right
and items whose key is known wrong (e.g. "A queue is last-in-first-out (FIFO)" marked correct).
The verifier (features/quiz/verify.py, one mid call per language) must keep every right item and
reject every wrong one.

    uv run python -m app.evals quiz-keys [--cloud]        # mock / local / cloud (in slot)"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SET = Path(__file__).with_name("quiz_key_set.json")
OUT = Path(__file__).resolve().parents[2] / "tests" / "evals" / "quiz" / "outputs"


def load() -> dict[str, Any]:
    return json.loads(SET.read_text(encoding="utf-8"))


def score(items: list[dict[str, Any]], kept: list[bool | None]) -> dict[str, Any]:
    """kept[i]: the verifier confirmed item i (None: it couldn't run)."""
    right = [k for it, k in zip(items, kept, strict=True) if it["key"] == "right"]
    wrong = [k for it, k in zip(items, kept, strict=True) if it["key"] == "wrong"]
    return {
        "right_kept": f"{sum(k is True for k in right)}/{len(right)}",
        "wrong_rejected": f"{sum(k is False for k in wrong)}/{len(wrong)}",
        "unavailable": sum(k is None for k in kept),
        "pass": all(k is True for k in right) and all(k is False for k in wrong),
    }


async def run(cloud: bool) -> int:
    import asyncio
    import time
    import uuid
    from datetime import UTC, datetime

    from app.core.config import get_settings
    from app.features.quiz import verify
    from app.jobs.registry import JobContext

    provider = get_settings().llm.provider
    if provider == "cloud" and not cloud:
        print("The provider is cloud; every call counts on our key. Add --cloud.")
        return 2
    data = load()

    async def no_stage(_stage: str) -> None:
        return None

    items, kept = data["items"], []
    by_lang: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        by_lang.setdefault(it["lang"], []).append(i)
    verdict: dict[int, bool | None] = {}
    for lang, idx in by_lang.items():  # one verifier call per language, like a real set
        ctx = JobContext(uuid.uuid4(), "EVAL", "background", {}, no_stage)
        qs = [items[i]["question"] for i in idx]
        for _ in range(6):
            ok = await verify.check(
                ctx,
                qs,
                context=data["context"],
                course="Fixtures",
                chapter="Answer keys",
                language=lang,
                lane="background",
            )
            if ok is not None:
                break
            await asyncio.sleep(10)  # mid busy: wait, then try again
        for i, good in zip(idx, ok if ok is not None else [None] * len(idx), strict=True):
            verdict[i] = good
            mark = "kept" if good else "unavailable" if good is None else "rejected"
            print(
                f"  {lang:5} key {items[i]['key']:5} → {mark}: {items[i]['question']['question']}"
            )
    kept = [verdict[i] for i in range(len(items))]
    result = score(items, kept)
    await asyncio.to_thread(OUT.mkdir, parents=True, exist_ok=True)
    path = OUT / f"{provider}-keys-{int(time.time())}.json"
    marked = [it | {"verifier_kept": k} for it, k in zip(items, kept, strict=True)]
    report = {"provider": provider, "generated_at": datetime.now(UTC).isoformat()}
    report |= result | {"items": marked}
    await asyncio.to_thread(
        path.write_text, json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"right kept {result['right_kept']} · wrong rejected {result['wrong_rejected']} → {path}")
    return 0 if result["pass"] else 1
