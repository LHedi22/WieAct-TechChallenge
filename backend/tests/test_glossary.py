"""Chapter glossary (audit OPT-11, N-5): one compact TRANSLATE_SHORT call per chapter × language
gives the fixed word for each of the chapter's concepts; notes, audio, tutor and grading prompts
carry it. No call when the material is in the student's language. The copied voice-rules example
«النهاية (limite)» is gone."""

from sqlalchemy import func, select

import app.gateway as gateway_module
from app import prompts
from app.features.glossary import service as glossary
from app.jobs.worker import Worker
from app.models import AICallLog
from tests.test_map import join
from tests.test_quiz import indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import api, as_user, pptx  # noqa: F401  (fixtures)

OWL_FR = as_user("NightOwl7", "fr")
GLOSSARY_PROMPTS = (
    "notes_write",
    "audio_script",
    "tutor_plan",
    "tutor_turn",
    "teachback_grade",
    "teachback_review",
)


def test_only_asked_terms_survive_once_each():
    content = {
        "terms": [
            {"term": "stack", "say": "pile"},
            {"term": "stack", "say": "autre"},
            {"term": "invented", "say": "x"},
            {"term": "queue", "say": ""},
            {"term": "LIFO", "say": "x" * 61},
            "junk",
        ]
    }
    assert glossary.valid(content, ["stack", "queue", "LIFO"]) == [("stack", "pile")]
    assert glossary.valid("not json", ["stack"]) == []


def test_the_block_is_empty_without_terms_and_lists_them_otherwise():
    assert glossary.block([]) == ""
    text = glossary.block([("stack", "مكدس"), ("LIFO", "LIFO")])
    assert "- stack → مكدس" in text and "- LIFO → LIFO" in text and "{" not in text


def test_the_prompts_carry_the_glossary_and_not_the_copied_example():
    assert "النهاية (limite)" not in prompts.voice_rules()
    for name in GLOSSARY_PROMPTS:
        _, messages = prompts.render(
            name,
            **dict.fromkeys(
                [
                    "language",
                    "level",
                    "style_note",
                    "course",
                    "chapter",
                    "context",
                    "goal",
                    "ideas",
                    "history",
                    "action",
                    "message",
                    "action_note",
                    "mode",
                    "prompt_label",
                    "prompt",
                    "answer",
                    "draft",
                ],
                "x",
            ),
            glossary="GLOSSARY-MARK",
        )
        assert "GLOSSARY-MARK" in messages[0]["content"], name


async def real_calls(sm, kind: str) -> int:
    async with sm() as s:
        return await s.scalar(
            select(func.count()).where(
                AICallLog.task_kind == kind,
                AICallLog.status_code == 200,
                AICallLog.cache_hit.is_(False),
            )
        )


async def test_one_glossary_call_per_language_reaches_notes_and_audio(api, sm, pptx, monkeypatch):  # noqa: F811, E501
    world, chapter = await indexed(api, sm, pptx)  # English slides, studied in French
    gull_fr = as_user("SeaGull3", "fr")
    await join(api, world, gull_fr)
    seen: dict[str, str] = {}
    real_run = gateway_module.run

    async def spy(task):
        seen[task.kind] = "\n".join(m["content"] for m in task.messages)
        return await real_run(task)

    monkeypatch.setattr(gateway_module, "run", spy)
    for building, who in (("studio", OWL_FR), ("audio", gull_fr)):  # two classmates
        r = await api.post(
            f"/api/{building}/{chapter}/generate", json={"level": "advanced"}, headers=who
        )
        assert r.status_code == 200, r.text
        await Worker(sm).drain(timeout_s=60)

    assert await real_calls(sm, "TRANSLATE_SHORT") == 1  # the audio episode read it from cache
    for kind in ("NOTES_WRITE", "AUDIO_SCRIPT"):
        assert "CHAPTER GLOSSARY" in seen[kind], kind


async def test_no_glossary_call_when_the_material_is_in_the_students_language(api, sm, pptx):  # noqa: F811, E501
    world, chapter = await indexed(api, sm, pptx)
    sea_en = as_user("SeaUrchin2", "en")
    await join(api, world, sea_en)
    r = await api.post(
        f"/api/studio/{chapter}/generate", json={"level": "advanced"}, headers=sea_en
    )
    assert r.status_code == 200, r.text
    await Worker(sm).drain(timeout_s=60)
    assert await real_calls(sm, "NOTES_WRITE") == 1
    assert await real_calls(sm, "TRANSLATE_SHORT") == 0


async def test_a_failed_glossary_call_never_blocks_the_pack(api, sm, pptx, monkeypatch):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    real_run = gateway_module.run

    async def broken(task):
        if task.kind == "TRANSLATE_SHORT":
            raise gateway_module.BadOutput("no glossary", refusal="bad_json")
        return await real_run(task)

    monkeypatch.setattr(gateway_module, "run", broken)
    r = await api.post(
        f"/api/studio/{chapter}/generate", json={"level": "advanced"}, headers=OWL_FR
    )
    await Worker(sm).drain(timeout_s=60)
    job = (await api.get(f"/api/jobs/{r.json()['job_id']}", headers=OWL_FR)).json()
    assert job["status"] == "done", job
    assert await real_calls(sm, "NOTES_WRITE") == 1
