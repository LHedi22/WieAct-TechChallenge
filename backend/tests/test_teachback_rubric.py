"""Audit N-2 (5 Nov, local models): every acceptable Teach-Back answer scored exactly 74 in every
language, the example score in the grading prompt's JSON template, so the score carried no signal.

Now the prompts carry no score at all (no anchor): the model rates four rubric criteria with
calibration examples, and the server adds the levels up. A graded set (weak, acceptable, strong,
off-topic and injected answers in en, fr, ar, ar-TN) feeds `python -m app.evals teachback`, whose
checks (scores vary, rank weak < acceptable < strong, same answer ≈ same score across languages)
are tested here on scripted graders."""

import re

import pytest

from app import prompts
from app.evals import teachback
from app.features.arena.service import CRITERIA, parse_grade

VALUES = dict(
    language="fr",
    mode="teaching a concept",
    course="Data Structures",
    chapter="Stacks and queues",
    context="[slide:1] A stack is LIFO.",
    prompt_label="CONCEPT",
    prompt="stack",
    answer="Une pile est LIFO.",
    draft="{}",
)


@pytest.mark.parametrize("name", ["teachback_grade", "teachback_review"])
def test_grading_prompts_carry_no_anchor_score(name):
    _, messages = prompts.render(name, **VALUES)
    system = messages[0]["content"]
    assert not re.search(r'"score"\s*:\s*\d', system), "a numeric score example anchors the model"
    assert "74" not in system
    for criterion in CRITERIA:  # the rubric is spelled out instead
        assert f'"{criterion}"' in system


def levels(accuracy, coverage, reasoning, example, **extra):
    c = {"accuracy": accuracy, "coverage": coverage, "reasoning": reasoning, "example": example}
    return {"flag": "ok", "criteria": {k: {"level": v} for k, v in c.items()}, **extra}


def test_the_server_totals_the_criteria_and_ignores_a_model_score():
    g = parse_grade(levels(3, 2, 1, 0, score=74, confidence="medium"))
    assert g.score == 60  # 10 points per level; the model's 74 is ignored
    assert parse_grade(levels(4, 3, 2, 1)).score == 100
    assert parse_grade(levels(1, 0, 0, 0)).score == 10


def test_levels_are_clamped_and_a_grade_without_criteria_is_unusable():
    assert parse_grade(levels(9, -2, "x", 1)).score == 50  # 4 + 0 + 0 + 1
    assert parse_grade({"flag": "ok", "score": 74}) is None  # no criteria: never finalised
    off = parse_grade({"flag": "off_topic"})
    assert off.flag == "off_topic" and off.score == 0


def test_the_graded_set_covers_five_kinds_in_four_languages():
    items = teachback.load_set()
    assert {(i["kind"], i["lang"]) for i in items} == {
        (k, lang) for k in teachback.KINDS for lang in ("en", "fr", "ar", "ar-TN")
    }
    assert all(len(i["text"]) >= 20 for i in items)  # the API's minimum answer length


def outcomes(score_of):
    return [{"kind": i["kind"], "lang": i["lang"], **score_of(i)} for i in teachback.load_set()]


def test_eval_checks_fail_a_constant_grader():
    flat = outcomes(lambda i: {"flag": "ok", "score": 74, "finalised": True})
    checks = teachback.checks(flat)
    assert not checks["scores_vary"] and not checks["ranks_weak_acceptable_strong"]
    assert not checks["off_topic_gets_nothing"] and not checks["injection_not_rewarded"]


def test_eval_checks_pass_a_grader_that_ranks_and_is_consistent():
    base = {"weak": 20, "acceptable": 50, "strong": 90}
    shift = {"en": 0, "fr": 10, "ar": 0, "ar-TN": -10}

    def score_of(i):
        if i["kind"] == "off_topic":
            return {"flag": "off_topic", "score": 0, "finalised": True}
        if i["kind"] == "injected":
            return {"flag": "ok", "score": 90, "finalised": False}  # held for review
        return {"flag": "ok", "score": base[i["kind"]] + shift[i["lang"]], "finalised": True}

    assert all(teachback.checks(outcomes(score_of)).values())


def test_eval_checks_catch_a_language_gap():
    def score_of(i):
        s = {"weak": 20, "acceptable": 50, "strong": 90}.get(i["kind"], 0)
        if i["lang"] == "ar-TN" and i["kind"] == "acceptable":
            s = 10  # the same answer judged much lower in Darija
        return {"flag": "ok" if s else "off_topic", "score": s, "finalised": True}

    assert not teachback.checks(outcomes(score_of))["same_answer_same_band_across_languages"]


def test_criteria_written_as_a_list_are_read_in_rubric_order_or_by_name():
    """Seen on llama3.1:8b (Phase 6 rerun): "criteria" came back as a list, and every Arabic
    grade was dropped as unusable."""
    by_order = parse_grade({"flag": "ok", "criteria": [{"level": 4}, {"level": 2}, {"level": 1}]})
    assert by_order.score == 70  # accuracy 4, coverage 2, reasoning 1, example missing → 0
    by_name = parse_grade(
        {
            "flag": "ok",
            "criteria": [{"name": "example", "level": 1}, {"name": "accuracy", "level": 3}],
        }
    )
    assert by_name.score == 40


def test_a_count_instead_of_a_list_does_not_drop_the_grade():
    """Phase 6 rerun: llama3.1:8b wrote "errors": 3 for an Arabic answer and the whole grade was
    dropped (the job failed)."""
    g = parse_grade({"flag": "off_topic", "criteria": [], "errors": 3, "missing": "x"})
    assert g is not None and g.flag == "off_topic" and g.errors == [] and g.missing == []
