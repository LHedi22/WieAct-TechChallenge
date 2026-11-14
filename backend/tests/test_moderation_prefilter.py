"""Audit OPT-07 (N-4, local): moderation was uneven across languages. The Darija insult was
published, a French study question rejected, and `personal_data` never came back. A server-side
pre-filter now settles the clear cases with no model call: Tunisian phone numbers, emails and
street addresses → personal_data; a short insult list (EN, FR, AR, Darija in Arabic script and
Arabizi; drafted, flagged _review) → abusive. Anything unclear still goes to the model."""

import pytest
from sqlalchemy import func, select

from app.core import economy
from app.features.arena import prefilter
from app.jobs.worker import Worker
from app.models import AICallLog
from tests.test_quiz import OWL_FR, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import SEA, api, pptx  # noqa: F401  (fixtures)


@pytest.mark.parametrize(
    "text",
    [
        "Call me on +216 22 345 678 to revise",
        "mon numéro 00216 98123456",
        "écris-moi: 55.123.456",
        "ابعثلي على 97 12 34 56",
        "my mail is owl.night@gmail.com",
        "I live at 12 rue de Marseille, can someone come over?",
        "نسكن في نهج ابن خلدون 15 تونس",
        "Avenue Habib Bourguiba 40, who wants to study together?",
    ],
)
def test_personal_data_is_caught_without_a_call(text):
    assert prefilter.check(text) == "personal_data"


@pytest.mark.parametrize(
    "text",
    [
        "Shut up you idiot, nobody cares about stacks",
        "t'es qu'un connard, c'est quoi une pile ?",
        "يا غبي ما فهمتش السؤال",
        "يا بهيم شنوة الـ stack",
        "ya 9a7ba chnowa el queue",
        "ZEBI 3lik w 3al stack",
        # group insults (the audit probe's cases, 2026-11-14)
        "You are all idiots, this class is garbage.",
        "Vous êtes tous des idiots, ce cours est nul.",
        "أنتم كلكم أغبياء وهذا القسم تافه.",
        "انتوما الكل بهايم والقسم هذا تافه.",
    ],
)
def test_clear_insults_are_caught_in_each_language(text):
    assert prefilter.check(text) == "abusive"


@pytest.mark.parametrize(
    "text",
    [
        "What is 23456789 mod 7?",
        "Why does @staticmethod not take self in Python?",
        "Is this a stupid question? Why is pop O(1)?",
        "Pourquoi une file est FIFO ? Je suis nul en algo",
        "شنوة الفرق بين stack و queue؟",
        "chnowa el far9 bin pile w file?",
        "Explain the limit of (x^2-1)/(x-1) as x→1, page 12",
        "In a 3 x 3 matrix, why is det(A) = 0 when two rows are equal?",
    ],
)
def test_study_questions_are_left_to_the_model(text):
    assert prefilter.check(text) is None


def test_the_insult_list_is_flagged_for_native_review():
    assert "_review" in prefilter.WORDS and set(prefilter.WORDS) >= {"en", "fr", "ar", "ar-TN"}


async def test_a_clear_case_is_rejected_and_refunded_with_no_model_call(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    r = await api.post(
        "/api/arena/questions",
        json={"chapter_id": chapter, "text": "ya 9a7ba, appelle-moi au +216 22 345 678"},
        headers=OWL_FR,
    )
    assert r.status_code == 202, r.text
    await Worker(sm).drain(timeout_s=30)
    mine = await api.get("/api/arena/questions", params={"chapter_id": chapter}, headers=OWL_FR)
    (item,) = mine.json()["questions"]
    assert item["status"] == "rejected" and item["reject_reason"] == "personal_data"
    assert (await api.get("/api/wallet", headers=OWL_FR)).json()["coins"] == (
        economy.DAILY_FREE_COINS
    )
    async with sm() as s:
        n = await s.scalar(select(func.count()).where(AICallLog.task_kind == "MODERATE_POST"))
    assert n == 0
    theirs = await api.get("/api/arena/questions", params={"chapter_id": chapter}, headers=SEA)
    assert theirs.json()["questions"] == []
