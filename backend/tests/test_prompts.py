"""Prompt rules shared by every student-facing prompt (app/prompts/_voice_rules.md): never address
the student by gender, keep technical terms in one fixed form, Tunisian Darija (not Egyptian or
formal Arabic) for ar-TN. Internal prompts (tagging, moderation) don't need them."""

import re
import string

import pytest

from app import prompts

STUDENT_FACING = [
    "audio_script",
    "daily_plan",
    "flashcards",
    "mind_map",
    "notes_write",
    "placement_quiz",
    "quiz_generate",
    "teachback_grade",
    "teachback_review",
    "tutor_guard",
    "tutor_plan",
    "tutor_summary",
    "tutor_turn",
    "wisdom_tip",
]


class Anything(dict):
    """Fills every {placeholder} so a template renders without its real inputs."""

    def __missing__(self, key: str) -> str:
        return f"<{key}>"


def render_system(name: str, language: str = "ar-TN") -> tuple[str, str]:
    version, sections = prompts._load(name)
    values = Anything(language=language)
    values["language_name"] = prompts.LANGUAGE_NAMES[language]
    values["voice_rules"] = prompts.voice_rules()
    return version, sections["system"].format_map(values)


@pytest.mark.parametrize("name", STUDENT_FACING)
def test_student_facing_prompts_carry_the_voice_rules(name):
    _, system = render_system(name)
    assert "gender" in system and "Tunisian Darija" in system and "technical term" in system


@pytest.mark.parametrize("name", STUDENT_FACING)
def test_each_rule_change_bumped_the_prompt_version(name):
    version, _ = prompts._load(name)
    raw = (prompts.DIR / f"{name}.md").read_text(encoding="utf-8")
    assert "{voice_rules}" in raw
    assert int(re.match(r"\d+", version).group()) >= 2


def test_render_fills_the_rules_without_extra_arguments():
    _, sections = prompts._load("tutor_turn")
    names = {
        f for text in sections.values() for _, f, _, _ in string.Formatter().parse(text) if f
    } - {"voice_rules", "language_name"}
    _, messages = prompts.render("tutor_turn", **{n: "x" for n in names} | {"language": "ar-TN"})
    assert "Egyptian" in messages[0]["content"]


def test_rules_file_is_versioned():
    assert prompts.voice_rules_version() >= 1
