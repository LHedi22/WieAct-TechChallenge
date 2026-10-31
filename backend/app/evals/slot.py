"""In-slot run: the AI features students use, in every UI language, saved for review.

    docker compose exec backend uv run python -m app.evals slot           # mock / local
    docker compose exec backend uv run python -m app.evals slot --cloud   # in our slot only

Drives the running API like the browser does (dev students `eval-<lang>`, `X-Dev-User`, which
production refuses) in the demo world, so jobs, coins, the queue and the class cache all take part:
per language one Study Studio pack, one Audio episode, the daily plan and two Teach-Back solo
answers (a solid one and a partial one, so grading has to tell them apart; graded once per
provider, later runs reuse the saved grades unless `--regrade`); then one Class Wisdom
tip for a new trap shared by three synthetic classmates (one call writes every member language).

Writes backend/tests/evals/slot/outputs/<provider>-<task>-<lang>.json with the outputs and an empty
`review` for the `prompt-evaluator` agent or a person, then exports the call stats for the report
(scripts/export_stats.py) when that script is reachable.

Shared outputs are generated once per chapter+level+language. Outputs already in the class cache are
saved with `"cached": true` and cost no call; on a dev database they may come from the mock, so
`--level` picks a level nothing was generated for yet (default: advanced).

It refuses to run on the cloud provider without `--cloud`: every call counts on our key.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

OUT = Path(__file__).resolve().parents[2] / "tests" / "evals" / "slot" / "outputs"
LANGS = ("en", "fr", "ar", "ar-TN")
TERMINAL = {"done", "failed", "cancelled"}
POLL_S = 1.5  # like the UI
TRAP_STUDENTS = ("seed-ana", "seed-bilel", "seed-cyrine")

# Teach-Back solo answers: one solid, one partial (misses "last in, first out" and the queue).
SOLO = {
    "en": (
        "A stack is last in, first out: push puts an item on top and pop takes the top one back, "
        "like a pile of plates. A queue is first in, first out: you enqueue at the back and "
        "dequeue at the front, like people waiting in line.",
        "A stack is a list where you put things and take them out again.",
    ),
    "fr": (
        "Une pile est LIFO, dernier entré premier sorti : push pose un élément au sommet et pop "
        "retire celui du sommet, comme une pile d'assiettes. Une file est FIFO : on ajoute à "
        "l'arrière et on retire à l'avant, comme une file d'attente.",
        "Une pile c'est une liste où on met des choses et on les reprend.",
    ),
    "ar": (
        "المكدس يعمل بمبدأ الداخل أخيرًا يخرج أولًا: عملية push تضع عنصرًا في القمة وعملية pop "
        "تأخذ العنصر الذي في القمة، مثل كومة الصحون. أما الطابور فالداخل أولًا يخرج أولًا: نضيف "
        "من الخلف ونحذف من الأمام، مثل صف الانتظار.",
        "المكدس هو قائمة نضع فيها أشياء ثم نأخذها.",
    ),
    "ar-TN": (
        "الـ stack يخدم بالـ LIFO: اللي يدخل اللخر يخرج الأول. push تحط حاجة الفوق و pop تنحّي "
        "اللي الفوق، كيف كدس الصحون. أما الـ queue فهي FIFO: نزيدو من التالي ونخرجو من القدام، "
        "كيف الصف قدام الكونتوار.",
        "الـ stack هي ليستة نحطو فيها حوايج ومن بعد ناخذوهم.",
    ),
}
SOLO_CONCEPT = "Stacks vs queues"


def _h(lang: str) -> dict[str, str]:
    return {"X-Dev-User": f"eval-{lang}", "X-UI-Language": lang}


async def _ok(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        raise RuntimeError(f"{r.request.method} {r.request.url.path} → {r.status_code} {r.text}")
    return r.json() if r.content else None


async def _wait(c: httpx.AsyncClient, job_id: str | None, timeout_s: float) -> dict[str, Any]:
    if not job_id:
        return {"status": "none"}
    t0 = time.monotonic()
    while True:
        view = await _ok(await c.get(f"/api/jobs/{job_id}"))
        if view["status"] in TERMINAL or time.monotonic() - t0 > timeout_s:
            return {k: view.get(k) for k in ("status", "error", "quick_mode", "result")} | {
                "wait_s": round(time.monotonic() - t0, 1)
            }
        await asyncio.sleep(POLL_S)


async def _coins(c: httpx.AsyncClient, lang: str, need: int) -> None:
    wallet = await _ok(await c.get("/api/wallet", headers=_h(lang)))
    while wallet["coins"] < need:  # demo purchase: no payment is taken in the hackathon build
        bought = await c.post(
            "/api/wallet/demo-purchase", json={"product": "coin_pack"}, headers=_h(lang)
        )
        wallet = (await _ok(bought))["wallet"]


def _graded_before(provider: str, lang: str) -> dict[str, Any] | None:
    """This provider's saved Teach-Back grades, if every answer was graded. Grading is personal
    (never cached), so sending the same answers again would be a repeated identical request."""
    path = OUT / f"{provider}-teachback_solo-{lang}.json"
    if not path.exists():
        return None
    saved = json.loads(path.read_text(encoding="utf-8"))["output"]
    done = all(a["job"].get("status") == "done" for a in saved.get("answers", []))
    return saved | {"reused": True} if done else None


async def _student(
    c: httpx.AsyncClient,
    lang: str,
    code: str,
    course: str,
    level: str,
    timeout_s: float,
    provider: str,
    regrade: bool,
) -> dict[str, dict[str, Any]]:
    """One student's run: start everything, then wait for each job. Returns {task: output}."""
    world = await _ok(await c.post("/api/worlds/join", json={"code": code}, headers=_h(lang)))
    chapter = next(ch for co in world["courses"] if co["name"] == course for ch in co["chapters"])
    ch = chapter["id"]
    await _coins(c, lang, 2 * 15 + 2 * 8)  # pack + episode + two solo answers (economy.py)

    async def started(path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = await c.post(path, json=body, headers=_h(lang))
        if r.status_code == 503:  # offline demo mode: AI is paused
            return {"error": r.json().get("detail")}
        return await _ok(r)

    pack = await started(f"/api/studio/{ch}/generate", {"level": level, "pay": "me"})
    episode = await started(f"/api/audio/{ch}/generate", {"level": level, "pay": "me"})
    graded = None if regrade else _graded_before(provider, lang)
    solos = [
        await started("/api/arena/solo", {"chapter_id": ch, "concept": SOLO_CONCEPT, "text": t})
        for t in ([] if graded else SOLO[lang])
    ]
    daily = await _ok(await c.get("/api/daily", headers=_h(lang)))

    out: dict[str, dict[str, Any]] = {}
    job = await _wait(c, pack.get("job_id"), timeout_s)
    studio = await _ok(await c.get(f"/api/studio/{ch}", params={"level": level}, headers=_h(lang)))
    cards = await _ok(
        await c.get(f"/api/studio/{ch}/cards", params={"level": level}, headers=_h(lang))
    )
    out["study_pack"] = {
        "started": pack,
        "job": job | {"result": None},
        "cached": bool(pack.get("cached")),
        "notes": studio["notes"],
        "map": studio["map"],
        "cards": [{k: x.get(k) for k in ("front", "back", "concept")} for x in cards["cards"]],
    }
    job = await _wait(c, episode.get("job_id"), timeout_s)
    audio = await _ok(await c.get(f"/api/audio/{ch}", params={"level": level}, headers=_h(lang)))
    out["audio"] = {
        "started": episode,
        "job": job | {"result": None},
        "cached": bool(episode.get("cached")),
        "script": audio["script"],
    }
    out["teachback_solo"] = graded or {
        "concept": SOLO_CONCEPT,
        "answers": [
            {
                "kind": kind,
                "text": text,
                "started": st,
                "job": await _wait(c, st.get("job_id"), timeout_s),
            }
            for kind, text, st in zip(("solid", "partial"), SOLO[lang], solos, strict=True)
        ],
    }
    job = await _wait(c, daily.get("plan_job_id"), timeout_s)
    daily = await _ok(await c.get("/api/daily", headers=_h(lang)))
    out["daily_plan"] = {
        "job": job,
        "planned_by": daily["planned_by"],
        "challenges": daily["challenges"],
    }
    out["_chapter"] = {"id": ch, "title": chapter["title"], "world_id": world["id"]}
    return out


async def _wisdom(
    c: httpx.AsyncClient, code: str, course: str, world_id: str, timeout_s: float
) -> dict[str, Any]:
    """Three synthetic classmates miss the same question, for the first concept that has no tip yet
    in this world: one WISDOM_TIP call writes it in every member language."""
    from sqlalchemy import select

    from app.core import db
    from app.models import WisdomTip, World
    from app.seed.wisdom import class_quiz_set, seed_wisdom, trap_concept

    sm = db.get_sessionmaker()
    async with sm() as s:
        world = await s.scalar(select(World).where(World.join_code == code))
        found = await class_quiz_set(s, world, course)
        if found is None:
            return {"skipped": "the class quiz set isn't ready yet"}
        _, qs, chapter = found
        tipped = set(
            await s.scalars(select(WisdomTip.concept).where(WisdomTip.world_id == world.id))
        )
    trap = next(
        (i for i, q in enumerate(qs.questions) if trap_concept(q, chapter) not in tipped), None
    )
    if trap is None:
        return {"skipped": "every concept of the class quiz set already has a tip"}
    jobs = await seed_wisdom(sm, code, course_name=course, trap=trap, students=TRAP_STUDENTS)
    waited = [await _wait(c, str(j), timeout_s) for j in jobs]
    tips = {}
    for lang in LANGS:
        got = await _ok(await c.get("/api/wisdom", params={"world_id": world_id}, headers=_h(lang)))
        concept = trap_concept(qs.questions[trap], chapter)
        tips[lang] = [t for t in got["tips"] if t.get("concept") == concept]
    return {"question": qs.questions[trap], "jobs": waited, "tips": tips}


def _save(provider: str, task: str, lang: str, data: dict[str, Any], meta: dict[str, Any]) -> Path:
    path = OUT / f"{provider}-{task}-{lang}.json"
    body = meta | {"task": task, "language": lang, "output": data}
    body["review"] = {"verdict": None, "notes": ""}  # filled by the reviewer
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


async def run(
    api: str,
    code: str,
    course: str,
    level: str,
    langs: list[str],
    cloud: bool,
    timeout_s: float,
    regrade: bool = False,
) -> int:
    async with httpx.AsyncClient(base_url=api, timeout=60) as c:
        status = await _ok(await c.get("/api/system/status"))
        provider = status["provider"]
        if status.get("app_env") == "production":
            print(
                "The dev students this run uses are refused in production: run it on the dev stack."
            )
            return 1
        if provider == "cloud" and not cloud:
            print("The API is on the cloud provider; every call counts on our key. Add --cloud.")
            return 1
        if status.get("offline_demo_mode"):
            print(f"AI is paused (offline demo mode); next slot: {status.get('next_slot')}")
            return 1
        stats0 = (await c.get("/api/admin/stats", params={"provider": provider})).json()
        print(f"provider {provider} · world {code} · {course} · level {level} · {', '.join(langs)}")
        t0 = time.monotonic()
        results = await asyncio.gather(
            *(
                _student(c, lang, code, course, level, timeout_s, provider, regrade)
                for lang in langs
            ),
            return_exceptions=True,
        )
        meta = {"provider": provider, "level": level, "generated_at": datetime.now(UTC).isoformat()}
        OUT.mkdir(parents=True, exist_ok=True)
        failed = 0
        world_id = None
        for lang, res in zip(langs, results, strict=True):
            if isinstance(res, BaseException):
                failed += 1
                print(f"{lang}: FAILED {type(res).__name__}: {res}")
                continue
            chapter = res.pop("_chapter")
            world_id = chapter["world_id"]
            for task, data in res.items():
                _save(provider, task, lang, data, meta | {"chapter": chapter["title"]})
            line = []
            for task, data in res.items():
                jobs = [data["job"]] if "job" in data else [a["job"] for a in data["answers"]]
                states = "/".join(j.get("status", "?") for j in jobs)
                tag = "cached" if data.get("cached") else "reused" if data.get("reused") else states
                line.append(f"{task} {tag}")
            print(f"{lang}: " + " · ".join(line))
        if world_id:
            tip = await _wisdom(c, code, course, world_id, timeout_s)
            _save(provider, "wisdom_tip", "all", tip, meta)
            states = "/".join(j["status"] for j in tip.get("jobs", []))
            print(
                f"wisdom: {tip.get('skipped') or states or 'no job (tip pending or failed before)'}"
            )
        stats1 = (await c.get("/api/admin/stats", params={"provider": provider})).json()
    print(f"done in {time.monotonic() - t0:.0f}s → {OUT}")
    print(_delta(stats0, stats1))
    _export_stats(api, provider)
    return 1 if failed else 0


def _delta(before: dict[str, Any], after: dict[str, Any]) -> str:
    """This run's share of /api/admin/stats (the same numbers the organisers compute)."""

    def flat(d: dict[str, Any]) -> dict[str, int]:
        tiers = d.get("by_tier") or {}
        return {
            "calls": d.get("calls", 0),
            "compact": tiers.get("compact", {}).get("calls", 0),
            "mid": tiers.get("mid", {}).get("calls", 0),
            "cache hits": d.get("cache_hits", 0),
            "repeated identical": d.get("repeated_identical", 0),
            "fallbacks": d.get("fallbacks", 0),
            "refusals": sum((d.get("refusals") or {}).values()),
        }

    a, b = flat(before), flat(after)
    return "this run: " + ", ".join(f"{k} {b[k] - a[k]}" for k in a)


def _export_stats(api: str, provider: str) -> None:
    script = Path(__file__).resolve().parents[3] / "scripts" / "export_stats.py"
    cmd = [sys.executable, str(script), "--api", api, "--provider", provider]
    if not script.exists():  # in the backend container: scripts/ isn't mounted
        print(f"stats: on the host run `python3 scripts/export_stats.py --provider {provider}`")
        return
    subprocess.run(cmd, check=False)  # noqa: S603 - our own script, fixed arguments
