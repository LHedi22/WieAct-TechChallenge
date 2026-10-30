"""Audio Studio: ONE mid AUDIO_SCRIPT call per chapter + level + language, then free for the class;
a classmate shares the running job; pool-payable; an unusable script refunds and is retried with a
fresh call."""

from app.core import economy
from app.features.audio import service as audio
from app.jobs.worker import Worker
from tests.test_quiz import OWL_FR, calls, indexed
from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_studio import coins
from tests.test_worlds_api import SEA, api, pptx  # noqa: F401  (fixtures)

LEVEL = {"level": "intermediate"}


async def episode(api, chapter, headers):  # noqa: F811
    r = await api.get(f"/api/audio/{chapter}", params=LEVEL, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def generate(api, chapter, headers, pay="me"):  # noqa: F811
    return await api.post(
        f"/api/audio/{chapter}/generate", json=LEVEL | {"pay": pay}, headers=headers
    )


async def test_one_mid_call_per_episode_then_free_for_the_class(api, sm, pptx):  # noqa: F811
    _, chapter = await indexed(api, sm, pptx)
    before = await episode(api, chapter, OWL_FR)
    assert before["script"] is None and before["cost"] == economy.COST["generate_shared_asset"]
    wallet = await coins(api, OWL_FR)
    start = (await generate(api, chapter, OWL_FR)).json()
    shared = (await generate(api, chapter, SEA)).json()
    assert shared == {"job_id": start["job_id"], "cost": 0, "cached": False}
    await Worker(sm).drain(timeout_s=60)
    job = (await api.get(f"/api/jobs/{start['job_id']}")).json()
    assert job["status"] == "done" and job["stages"] == ["reading_chapter", "writing_script"]
    assert await coins(api, OWL_FR) == wallet - economy.COST["generate_shared_asset"]

    after = await episode(api, chapter, SEA)
    assert after["cost"] == 0 and after["cached"] and len(after["script"]["segments"]) >= 3
    assert (await generate(api, chapter, SEA)).json() == {"job_id": None, "cost": 0, "cached": True}
    assert await calls(sm, "AUDIO_SCRIPT") == 1
    assert await calls(sm, "NOTES_WRITE") == 0  # the study pack is a separate purchase


async def test_unusable_script_refunds_the_pool_and_a_retry_calls_again(  # noqa: F811
    api,  # noqa: F811
    sm,
    pptx,  # noqa: F811
    monkeypatch,
):
    from mock_llm import app as mock_app

    world, chapter = await indexed(api, sm, pptx)
    pool_url = f"/api/worlds/{world['id']}/pool"
    await api.post(pool_url, json={"amount": 20}, headers=SEA)
    real = mock_app.GENERATORS["AUDIO_SCRIPT"]
    monkeypatch.setitem(mock_app.GENERATORS, "AUDIO_SCRIPT", lambda *a, **k: {"segments": []})
    start = (await generate(api, chapter, OWL_FR, pay="pool")).json()
    await Worker(sm).drain(timeout_s=60)
    assert (await api.get(f"/api/jobs/{start['job_id']}")).json()["status"] == "failed"
    assert (await api.get(pool_url, headers=SEA)).json()["balance"] == 20

    monkeypatch.setitem(mock_app.GENERATORS, "AUDIO_SCRIPT", real)
    await generate(api, chapter, OWL_FR, pay="pool")
    await Worker(sm).drain(timeout_s=60)
    assert (await episode(api, chapter, OWL_FR))["script"]["segments"]
    assert (await api.get(pool_url, headers=SEA)).json()["balance"] == 5
    assert await calls(sm, "AUDIO_SCRIPT") == 2  # a fresh call, not the cached bad reply


def test_script_validation():
    assert audio.valid_script({"segments": ["a", " ", "b"]}) is None
    ok = audio.valid_script({"title": "T", "segments": ["a", "b", "c", 4]})
    assert ok == {"title": "T", "segments": ["a", "b", "c"]}
