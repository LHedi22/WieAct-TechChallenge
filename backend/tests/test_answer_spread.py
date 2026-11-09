"""Correct options are spread over A–D (9 Nov: llama3.2-3b put every answer at index 0)."""

import uuid

from app.features.placement.service import clean
from app.features.quiz.pool import spread_answers, valid_questions
from app.models import Chapter


def _q(i: int, answer: int = 0) -> dict:
    opts = [f"option {i}-{k}" for k in range(4)]
    return {
        "question": f"Question number {i} about recommendation reports?",
        "options": opts,
        "answer_index": answer,
        "hint": "h",
        "explanation": "e",
        "concept": "c",
    }


def test_all_first_answers_get_spread_and_stay_correct():
    raw = [_q(i) for i in range(10)]
    out = valid_questions({"questions": raw})
    assert len(out) == 10
    for before, after in zip(raw, out, strict=True):
        # the key still points at the same option text, and no option is lost
        assert after["options"][after["answer_index"]] == before["options"][0]
        assert sorted(after["options"]) == sorted(before["options"])
    positions = {q["answer_index"] for q in out}
    assert len(positions) >= 3  # not "always A"


def test_spread_is_deterministic_and_idempotent():
    once = spread_answers([_q(i) for i in range(10)])
    assert spread_answers([_q(i) for i in range(10)]) == once
    assert spread_answers([dict(q, options=list(q["options"])) for q in once]) == once


def test_placement_questions_are_spread_too():
    chapters = [Chapter(id=uuid.uuid4(), idx=1, title="Ch 1")]
    raw = [_q(i) | {"chapter": 1, "difficulty": "intermediate"} for i in range(8)]
    out = clean({"questions": raw}, chapters)
    assert out, "placement questions validated"
    for before, after in zip(raw, out, strict=False):
        assert after["options"][after["answer_index"]] == before["options"][0]
    assert len({q["answer_index"] for q in out}) >= 3
