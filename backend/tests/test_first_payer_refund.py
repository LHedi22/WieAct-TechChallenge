# ruff: noqa: F811  (pytest fixtures imported from other test modules)
"""First-payer refund: a student who paid for a class asset (study pack, audio episode, quiz set)
gets part of it back once 3 classmates have opened it (economy.FIRST_PAYER_REFUND_*). One
`share_back` ledger row per paid job, never for what the class got for free (a prefetch, the
upload's quiz set, an asset the Class Pool paid), and the wallet always equals its ledger."""

import uuid

from sqlalchemy import select

from app.admin import invariants
from app.core import economy
from app.jobs.worker import Worker
from app.models import CoinLedger, User
from tests.test_map import join
from tests.test_prefetch import (
    KID,
    plan_world,
    prefetch_jobs,
    roomy_mock,  # noqa: F401  (fixture)
    settle,
    two_chapters,
)
from tests.test_quiz import OWL_FR, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_studio import coins
from tests.test_worlds_api import SEA, api, as_user, pptx  # noqa: F401  (fixtures)

LEVEL = {"level": "intermediate"}
CLASSMATES = [as_user(f"Classmate{i}", "fr") for i in range(1, 5)]
PRICE = economy.COST["generate_shared_asset"]


def back(price: int) -> int:
    num, den = economy.FIRST_PAYER_REFUND_SHARE
    return price * num // den


async def share_backs(sm) -> list[CoinLedger]:
    async with sm() as s:
        return list(await s.scalars(select(CoinLedger).where(CoinLedger.kind == "share_back")))


async def clean(sm, *nicknames: str) -> None:
    """Every economy invariant holds for these students, wallet == ledger included."""
    async with sm() as s:
        for nick in nicknames:
            user = await s.scalar(select(User).where(User.nickname == nick))
            assert invariants.flat(await invariants.run(s, user.id)) == [], nick


async def open_studio(api, chapter, headers) -> None:
    r = await api.get(f"/api/studio/{chapter}", params=LEVEL, headers=headers)
    assert r.status_code == 200 and r.json()["notes"], r.text


async def open_audio(api, chapter, headers) -> None:
    r = await api.get(f"/api/audio/{chapter}", params=LEVEL, headers=headers)
    assert r.status_code == 200 and r.json()["script"], r.text


async def test_the_payer_gets_part_of_a_pack_back_after_three_classmates_open_it(api, sm, pptx):
    world, chapter = await indexed(api, sm, pptx)
    for c in CLASSMATES:
        await join(api, world, c)
    r = await api.post(
        f"/api/studio/{chapter}/generate", json=LEVEL | {"pay": "me"}, headers=OWL_FR
    )
    assert r.json()["cost"] == PRICE
    await Worker(sm).drain(timeout_s=60)
    paid = await coins(api, OWL_FR)

    await open_studio(api, chapter, OWL_FR)  # the payer's own visits don't count
    for c in CLASSMATES[:2]:
        for _ in range(3):  # nor do repeated visits by the same classmate
            await open_studio(api, chapter, c)
    assert await share_backs(sm) == [] and await coins(api, OWL_FR) == paid

    await open_studio(api, chapter, CLASSMATES[2])  # the third classmate
    assert await coins(api, OWL_FR) == paid + back(PRICE) == paid + 10
    await open_studio(api, chapter, CLASSMATES[3])  # paid once, whoever comes next
    await open_studio(api, chapter, CLASSMATES[2])
    [row] = await share_backs(sm)
    assert (row.bucket, row.delta) == ("earned", back(PRICE))
    assert await coins(api, OWL_FR) == paid + back(PRICE)
    await clean(sm, "NightOwl7", "Classmate1", "Classmate3")


async def test_audio_and_quiz_sets_pay_back_too(api, sm, pptx):
    world, chapter = await indexed(api, sm, pptx)
    for c in CLASSMATES[:3]:
        await join(api, world, c)
    await api.post(f"/api/audio/{chapter}/generate", json=LEVEL | {"pay": "me"}, headers=OWL_FR)
    # a quiz set of its own: the upload made seed 1 for free, so finish it and pay for seed 2
    body = {"chapter_id": chapter, "level": "intermediate"}
    first = (await api.post("/api/quiz/start", json=body, headers=OWL_FR)).json()
    await api.post(f"/api/quiz/attempts/{first['attempt_id']}/finish", headers=OWL_FR)
    assert (await api.post("/api/quiz/start", json=body, headers=OWL_FR)).json()["cost"] == 5
    await Worker(sm).drain(timeout_s=60)
    paid = await coins(api, OWL_FR)

    for c in CLASSMATES[:3]:
        await open_audio(api, chapter, c)
        # each classmate takes the free seed-1 set first (made by the upload: nobody to pay
        # back), then the set the payer bought
        for _ in range(2):
            start = (await api.post("/api/quiz/start", json=body, headers=c)).json()
            assert start["cost"] == 0 and start["attempt_id"], start
            await api.post(f"/api/quiz/attempts/{start['attempt_id']}/finish", headers=c)
    rows = await share_backs(sm)
    assert sorted(r.delta for r in rows) == sorted([back(PRICE), back(economy.COST["quiz"])])
    assert await coins(api, OWL_FR) == paid + back(PRICE) + back(economy.COST["quiz"])
    await clean(sm, "NightOwl7", "Classmate2")


async def test_nothing_is_paid_back_for_free_content(api, sm, pptx, monkeypatch):
    """Prefetched (ownerless, 0 coins) and Class Pool packs have no student who paid."""
    world, _, ch2 = await two_chapters(api, sm, pptx, monkeypatch)
    for c in CLASSMATES:
        await join(api, world, c)
    await plan_world(sm, world, chapter_id=uuid.UUID(ch2), level="intermediate", language="fr")
    await settle(sm)
    assert {j.kind for j in await prefetch_jobs(sm, ch2)} >= {"STUDY_PACK", "AUDIO_EPISODE"}
    for c in [KID, *CLASSMATES]:
        await open_studio(api, ch2, c)
        await open_audio(api, ch2, c)
    assert await share_backs(sm) == []

    # chapter 1's pack, paid by the Class Pool
    ch1 = world["course"]["chapters"][0]["id"]
    await api.post(f"/api/worlds/{world['id']}/pool", json={"amount": 20}, headers=SEA)
    r = await api.post(f"/api/studio/{ch1}/generate", json=LEVEL | {"pay": "pool"}, headers=KID)
    assert r.json()["cost"] == PRICE
    await Worker(sm).drain(timeout_s=60)
    for c in CLASSMATES:
        await open_studio(api, ch1, c)
    assert await share_backs(sm) == []
    await clean(sm, "Classmate1")
