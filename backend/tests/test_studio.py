"""Study Studio: one pack (notes + deck + mind map) per chapter + level + language for 1 mid + 2
compact calls, then free for the class; shared pending job; paid by the student or the Class Pool
(refunded on failure); a failed map keeps the notes and cards; SRS reviews count toward a daily
`flashcards` challenge; quiz cards are personal and cost no AI call."""

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core import economy
from app.features.daily import plan
from app.features.studio import pack
from app.jobs.worker import Worker
from app.models import AICallLog, ClassPoolLedger, DailyState, Flashcard, StudyAsset
from tests.test_quiz import OWL_FR, answers_of, calls, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import SEA, api, as_user, pptx  # noqa: F401  (fixtures)

LEVEL = {"level": "intermediate"}


async def studio(api, chapter, headers):  # noqa: F811
    r = await api.get(f"/api/studio/{chapter}", params=LEVEL, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def generate(api, chapter, headers, pay="me"):  # noqa: F811
    return await api.post(
        f"/api/studio/{chapter}/generate", json=LEVEL | {"pay": pay}, headers=headers
    )


async def coins(api, headers) -> int:  # noqa: F811
    return (await api.get("/api/wallet", headers=headers)).json()["coins"]


async def test_one_pack_costs_one_mid_and_two_compact_calls_then_is_free(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    before = await studio(api, chapter, OWL_FR)
    assert before["notes"] is None and before["missing"] == ["notes", "flashcards", "map"]
    assert before["cost"] == economy.COST["generate_shared_asset"] and not before["cached"]
    wallet = await coins(api, OWL_FR)

    start = (await generate(api, chapter, OWL_FR)).json()
    assert start["job_id"] and start["cost"] == economy.COST["generate_shared_asset"]
    shared = (await generate(api, chapter, SEA)).json()  # a classmate meanwhile: same job, free
    assert shared == {"job_id": start["job_id"], "cost": 0, "cached": False}
    assert await coins(api, OWL_FR) == wallet - economy.COST["generate_shared_asset"]

    await Worker(sm).drain(timeout_s=60)
    job = (await api.get(f"/api/jobs/{start['job_id']}")).json()
    assert job["status"] == "done" and job["result"]["missing"] == []
    assert job["stages"] == ["reading_chapter", "writing_notes", "making_flashcards", "drawing_map"]
    assert (await calls(sm, "NOTES_WRITE"), await calls(sm, "FLASHCARDS")) == (1, 1)
    assert await calls(sm, "MAP_WRITE") == 1

    after = await studio(api, chapter, SEA)
    assert after["missing"] == [] and after["cost"] == 0 and after["cached"]
    assert after["notes"]["sections"] and after["map"]["branches"]
    assert after["cards"]["new"] == after["cards"]["total"] >= pack.MIN_CARDS
    refs = {r for sec in after["notes"]["sections"] for r in sec["refs"]}
    assert refs and all(r.startswith("slide:") for r in refs)  # only refs we sent
    price = await api.get(f"/api/studio/{chapter}/price", params=LEVEL, headers=SEA)
    assert price.json() == {"cost": 0, "cached": True}
    again = (await generate(api, chapter, SEA)).json()
    assert again == {"job_id": None, "cost": 0, "cached": True}
    assert await calls(sm, "NOTES_WRITE") == 1  # nothing generated twice


async def test_pool_pays_and_a_failed_pack_refunds_the_pool(api, sm, pptx, monkeypatch):  # noqa: F811
    from mock_llm import app as mock_app

    world, chapter = await indexed(api, sm, pptx)
    pool_url = f"/api/worlds/{world['id']}/pool"
    short = await generate(api, chapter, OWL_FR, pay="pool")
    assert short.status_code == 402 and short.json()["detail"] == "errors.pool_insufficient"
    await api.post(pool_url, json={"amount": 20}, headers=SEA)
    wallet = await coins(api, OWL_FR)

    monkeypatch.setitem(mock_app.GENERATORS, "NOTES_WRITE", lambda *a, **k: {"text": "?"})
    start = (await generate(api, chapter, OWL_FR, pay="pool")).json()
    assert (await api.get(pool_url, headers=SEA)).json()["balance"] == 5
    await Worker(sm).drain(timeout_s=60)
    job = (await api.get(f"/api/jobs/{start['job_id']}")).json()
    assert job["status"] == "failed"
    assert (await api.get(pool_url, headers=SEA)).json()["balance"] == 20  # refunded
    assert await coins(api, OWL_FR) == wallet  # the student's wallet was never touched
    async with sm() as s:
        kinds = sorted(r.kind for r in await s.scalars(select(ClassPoolLedger)))
        assert kinds == ["contribute", "refund", "spend"]
        assert await s.scalar(select(func.count()).select_from(StudyAsset)) == 0


async def test_a_failed_map_keeps_the_notes_and_cards_and_a_free_run_fills_it(  # noqa: F811
    api,  # noqa: F811
    sm,
    pptx,  # noqa: F811
    monkeypatch,
):
    from mock_llm import app as mock_app

    _, chapter = await indexed(api, sm, pptx)
    real = mock_app.GENERATORS["MAP_WRITE"]
    monkeypatch.setitem(mock_app.GENERATORS, "MAP_WRITE", lambda *a, **k: {"root": ""})
    start = (await generate(api, chapter, OWL_FR)).json()
    await Worker(sm).drain(timeout_s=60)
    job = (await api.get(f"/api/jobs/{start['job_id']}")).json()
    assert job["status"] == "done" and job["result"]["missing"] == ["map"]
    view = await studio(api, chapter, SEA)
    assert view["notes"] and view["map"] is None and view["cards"]["total"] > 0
    assert view["missing"] == ["map"] and view["cost"] == 0  # the class already paid

    monkeypatch.setitem(mock_app.GENERATORS, "MAP_WRITE", real)
    wallet = await coins(api, SEA)
    retry = (await generate(api, chapter, SEA)).json()
    assert retry["cost"] == 0 and retry["job_id"]
    await Worker(sm).drain(timeout_s=60)
    assert (await studio(api, chapter, SEA))["map"]["branches"]
    assert await coins(api, SEA) == wallet
    assert await calls(sm, "NOTES_WRITE") == 1 and await calls(sm, "FLASHCARDS") == 1


async def test_reviews_schedule_cards_and_count_toward_the_daily_challenge(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    await generate(api, chapter, OWL_FR)
    await Worker(sm).drain(timeout_s=60)
    await api.get("/api/daily", headers=OWL_FR)  # today's row exists
    async with sm() as s:
        state = await s.scalar(select(DailyState))
        state.challenges = [plan.challenge("flashcards", 10, None)] + state.challenges[1:]
        await s.commit()

    queue = (await api.get(f"/api/studio/{chapter}/cards", params=LEVEL, headers=OWL_FR)).json()
    first = queue["cards"][0]
    assert first["stage"] == "new" and first["intervals"] == {
        "again": 60,
        "good": 600,
        "easy": 259200,
    }
    total = queue["counts"]["total"]
    for card, grade in zip(queue["cards"][:3], ("again", "good", "easy"), strict=True):
        r = await api.post(
            f"/api/studio/cards/{card['id']}/review", json={"grade": grade}, headers=OWL_FR
        )
        assert r.status_code == 200
    queue = (await api.get(f"/api/studio/{chapter}/cards", params=LEVEL, headers=OWL_FR)).json()
    assert queue["counts"]["new"] == total - 3 and queue["next_due_at"]
    assert first["id"] not in [c["id"] for c in queue["cards"]]  # due in a minute, not now
    daily = (await api.get("/api/daily", headers=OWL_FR)).json()
    assert (
        daily["challenges"][0]["type"] == "flashcards" and daily["challenges"][0]["progress"] == 3
    )

    stranger = as_user("Stranger9")
    r = await api.post(
        f"/api/studio/cards/{first['id']}/review", json={"grade": "good"}, headers=stranger
    )
    assert r.status_code == 404
    assert (
        await api.get(f"/api/studio/{chapter}", params=LEVEL, headers=stranger)
    ).status_code == 404


async def test_missed_quiz_questions_become_personal_cards_without_ai(api, sm, pptx):  # noqa: F811
    world, chapter = await indexed(api, sm, pptx)
    body = {"chapter_id": chapter, "level": "intermediate"}
    aid = (await api.post("/api/quiz/start", json=body, headers=OWL_FR)).json()["attempt_id"]
    right = await answers_of(sm)
    for _ in range(2):  # question 0 wrong twice
        await api.post(
            f"/api/quiz/attempts/{aid}/answer",
            json={"q": 0, "choice": (right[0] + 1) % 4},
            headers=OWL_FR,
        )
    early = await api.post(f"/api/quiz/attempts/{aid}/flashcards", headers=OWL_FR)
    assert early.status_code == 400
    await api.post(f"/api/quiz/attempts/{aid}/finish", headers=OWL_FR)  # the rest: skipped
    log_before = await total_calls(sm)
    out = (await api.post(f"/api/quiz/attempts/{aid}/flashcards", headers=OWL_FR)).json()
    assert out["added"] == 10 and out["chapter_id"] == chapter
    again = (await api.post(f"/api/quiz/attempts/{aid}/flashcards", headers=OWL_FR)).json()
    assert again["added"] == 0  # idempotent
    assert await total_calls(sm) == log_before

    mine = (await api.get(f"/api/studio/{chapter}/cards", params=LEVEL, headers=OWL_FR)).json()
    assert mine["counts"]["total"] == 10 and mine["cards"][0]["source"] == "quiz"
    theirs = (await api.get(f"/api/studio/{chapter}/cards", params=LEVEL, headers=SEA)).json()
    assert theirs["counts"]["total"] == 0  # personal
    async with sm() as s:
        card = await s.scalar(select(Flashcard).where(Flashcard.ref == f"{aid}:0"))
        assert card.user_id is not None and card.back
    other = await api.post(f"/api/quiz/attempts/{aid}/flashcards", headers=SEA)
    assert other.status_code == 404


async def total_calls(sm) -> int:
    async with sm() as s:
        return await s.scalar(select(func.count()).select_from(AICallLog))


def test_validation_keeps_what_is_usable():
    notes = pack.valid_notes(
        {
            "title": "T",
            "sections": [
                {"heading": "A", "points": ["x", " "], "refs": ["page:1", "page:99"]},
                {"heading": "", "points": ["y"]},
                {"heading": "B", "points": []},
            ],
            "key_terms": [{"term": "t", "meaning": "m"}, {"term": ""}],
        },
        {"page:1"},
    )
    assert notes == {
        "title": "T",
        "sections": [{"heading": "A", "points": ["x"], "refs": ["page:1"]}],
        "key_terms": [{"term": "t", "meaning": "m"}],
    }
    assert pack.valid_notes({"sections": []}) is None and pack.valid_notes("oops") is None
    cards = pack.valid_cards(
        {"cards": [{"front": "Q1", "back": "A"}, {"front": "q1", "back": "B"}]}
    )
    assert [c["front"] for c in cards] == ["Q1"]
    assert pack.valid_map({"root": "R", "branches": [{"label": "a"}]}) is None
    tree = pack.valid_map(
        {"root": "R", "branches": [{"label": "a"}, {"label": "b", "children": ["c"]}]}
    )
    assert tree == {
        "root": "R",
        "branches": [{"label": "a", "children": []}, {"label": "b", "children": ["c"]}],
    }


def test_flashcards_are_planned_only_for_students_with_cards():
    ai = {"challenges": [{"type": "flashcards", "target": 12}], "message": "Go"}
    fallback = plan.rule_plan([], datetime.now(UTC).date())
    with_cards, _ = plan.from_ai(ai, [], fallback, has_cards=True)
    assert with_cards[0]["type"] == "flashcards" and with_cards[0]["target"] == 10
    without, _ = plan.from_ai(ai, [], fallback, has_cards=False)
    assert "flashcards" not in [c["type"] for c in without]
