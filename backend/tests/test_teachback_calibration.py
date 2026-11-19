"""Audit OPT-16 (residual N-2, local models): Arabic and Darija answers did not rank weak <
acceptable < strong. The shared rubric now has one calibration example per level in English,
Arabic and Darija (Arabic script), and every example is internally consistent: each "evidence"
is copied exactly from its example text, as the server requires of real grades."""

import json
import re

import pytest

from app import prompts

LINE = re.compile(r'^- (?:\((?P<lang>\w+)\) )?"(?P<text>[^"]+)" → (?P<grade>\{.*\})$')


def examples() -> list[dict]:
    out = []
    for line in prompts.fragment("teachback_rubric").splitlines():
        m = LINE.match(line)
        if m:
            out.append({"lang": m["lang"] or "English", "text": m["text"],
                        "grade": json.loads(m["grade"])})  # fmt: skip
    return out


def total(grade: dict) -> int:
    return sum(v.get("level", 0) for v in grade.values() if isinstance(v, dict))


@pytest.mark.parametrize("lang", ["English", "Arabic", "Darija"])
def test_each_language_has_a_weak_an_acceptable_and_a_strong_example(lang):
    graded = [e for e in examples() if e["lang"] == lang]
    assert len(graded) == 3, graded
    totals = [total(e["grade"]) for e in graded]
    assert totals == sorted(totals) and len(set(totals)) == 3  # weak < acceptable < strong


def test_every_evidence_is_copied_from_its_example():
    for e in examples():
        for criterion, v in e["grade"].items():
            if v.get("level", 0) > 0:
                assert v["evidence"] in e["text"], (e["lang"], criterion, v["evidence"])


def test_the_same_idea_gets_the_same_levels_in_every_language():
    by_lang: dict[str, list[dict]] = {}
    for e in examples():
        by_lang.setdefault(e["lang"], []).append(e["grade"])
    levels = {
        lang: [{k: v["level"] for k, v in g.items()} for g in grades]
        for lang, grades in by_lang.items()
    }
    assert levels["Arabic"] == levels["English"] == levels["Darija"]
