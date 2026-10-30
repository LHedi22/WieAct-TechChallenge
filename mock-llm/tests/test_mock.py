import asyncio
import json

import httpx
import pytest

from mock_llm.app import create_app
from mock_llm.config import MockConfig

FAST = dict(latency_compact_ms=(0, 0), latency_mid_ms=(0, 0), p_503_mid=0, p_bad_json=0)


def client(**cfg) -> httpx.AsyncClient:
    app = create_app(MockConfig(**(FAST | cfg)), seed=1)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mock")


def chat_body(model="mock-compact", system="", user="limits 0/0", **extra):
    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": user}
    ]
    return {"model": model, "messages": msgs, "max_tokens": 200} | extra


async def test_models_list():
    async with client() as c:
        ids = [m["id"] for m in (await c.get("/v1/models")).json()["data"]]
    assert ids == ["mock-compact", "mock-mid", "mock-embed"]


async def test_chat_returns_whole_response_with_quota_headers():
    async with client() as c:
        r = await c.post("/v1/chat/completions", json=chat_body())
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"].startswith("Mock reply")
    assert r.json()["usage"]["completion_tokens"] > 0
    assert int(r.headers["x-ratelimit-remaining"]) >= 0
    assert "x-ratelimit-reset-ms" in r.headers


async def test_quota_header_names_are_configurable():
    async with client(header_remaining="x-team-left") as c:
        r = await c.post("/v1/chat/completions", json=chat_body())
    assert "x-team-left" in r.headers


async def test_task_fixture_by_marker_and_language():
    system = "<!-- task: DEMO_SUMMARY --> <!-- lang: fr --> Résume."
    async with client() as c:
        r = await c.post("/v1/chat/completions", json=chat_body(system=system, user="les limites"))
    data = json.loads(r.json()["choices"][0]["message"]["content"])
    assert "limite" in data["summary"] and "les limites" in data["summary"]
    assert len(data["key_points"]) == 3


async def test_streaming_rejected():
    async with client() as c:
        r = await c.post("/v1/chat/completions", json=chat_body(stream=True))
    assert r.status_code == 400


async def test_ceiling_400_names_the_limit():
    async with client(max_tokens_ceiling=512) as c:
        r = await c.post("/v1/chat/completions", json=chat_body(max_tokens=2000))
    assert r.status_code == 400
    assert "512" in r.json()["error"]["message"]


@pytest.mark.parametrize("fault,status", [("503", 503), ("quota", 429), ("blocked", 401)])
async def test_fault_header(fault, status):
    async with client() as c:
        r = await c.post("/v1/chat/completions", json=chat_body(), headers={"X-Mock-Fault": fault})
    assert r.status_code == status
    if fault == "503":
        assert r.headers["Retry-After"] == "3"
    if fault == "quota":
        assert "quota" in r.json()["error"]["message"] and int(r.headers["Retry-After"]) >= 1
    if fault == "blocked":
        assert r.json()["error"]["message"] == "Key is blocked"


async def test_quota_status_configurable():
    async with client(quota_status=403) as c:
        r = await c.post(
            "/v1/chat/completions", json=chat_body(), headers={"X-Mock-Fault": "quota"}
        )
    assert r.status_code == 403


async def test_bad_json_fault():
    system = "<!-- task: DEMO_SUMMARY -->"
    async with client() as c:
        r = await c.post(
            "/v1/chat/completions",
            json=chat_body(system=system),
            headers={"X-Mock-Fault": "badjson"},
        )
    text = r.json()["choices"][0]["message"]["content"]
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


async def test_bucket_empties_then_refuses_with_delay():
    async with client(rpm=6, burst=2) as c:
        codes = [
            (await c.post("/v1/chat/completions", json=chat_body())).status_code for _ in range(3)
        ]
        last = await c.post("/v1/chat/completions", json=chat_body())
    assert codes[:2] == [200, 200] and codes[2] == 429
    assert int(last.headers["Retry-After"]) >= 1


async def test_more_than_two_concurrent_rejected():
    async with client(latency_compact_ms=(200, 200)) as c:
        rs = await asyncio.gather(
            *[c.post("/v1/chat/completions", json=chat_body()) for _ in range(4)]
        )
        stats = (await c.get("/_mock/stats")).json()
    assert sorted(r.status_code for r in rs) == [200, 200, 429, 429]
    assert stats["max_concurrency_seen"] == 2


async def test_blocked_and_live_config_patch():
    async with client(blocked=True) as c:
        assert (await c.post("/v1/chat/completions", json=chat_body())).status_code == 401
        await c.patch("/_mock/config", json={"blocked": False})
        assert (await c.post("/v1/chat/completions", json=chat_body())).status_code == 200


async def test_mid_503_probability():
    async with client(p_503_mid=1.0) as c:
        r = await c.post("/v1/chat/completions", json=chat_body(model="mock-mid"))
        ok = await c.post("/v1/chat/completions", json=chat_body(model="mock-compact"))
    assert r.status_code == 503 and ok.status_code == 200


async def test_embeddings_deterministic_and_sized():
    async with client(embedding_dim=8) as c:
        a = (
            await c.post("/v1/embeddings", json={"model": "mock-embed", "input": ["x", "y"]})
        ).json()
        b = (await c.post("/v1/embeddings", json={"model": "mock-embed", "input": "x"})).json()
    assert len(a["data"]) == 2 and len(a["data"][0]["embedding"]) == 8
    assert a["data"][0]["embedding"] == b["data"][0]["embedding"]
    assert a["data"][0]["embedding"] != a["data"][1]["embedding"]


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_embeddings_reflect_shared_words():
    texts = [
        "limit 0/0 indeterminate form: factor and cancel before substitution",
        "the derivative is the slope of the tangent line, power rule",
        "limit 0/0",
    ]
    async with client() as c:
        r = await c.post("/v1/embeddings", json={"model": "mock-embed", "input": texts})
    a, b, q = (d["embedding"] for d in r.json()["data"])
    assert _cos(q, a) > _cos(q, b) + 0.2


async def test_chunk_tag_fixture_answers_every_chunk():
    user = (
        "[[chunk:c1]] Limits and the indeterminate form, limits again\n[[chunk:c2]] Pile de plates"
    )
    body = chat_body(system="Tag. <!-- task: CHUNK_TAG --> <!-- lang: en -->", user=user)
    async with client() as c:
        out = json.loads(
            (await c.post("/v1/chat/completions", json=body)).json()["choices"][0]["message"][
                "content"
            ]
        )
    assert [ch["id"] for ch in out["chunks"]] == ["c1", "c2"]
    assert out["chunks"][0]["concepts"][0] == "limits"


async def test_quiz_fixture_ten_questions_in_language():
    body = chat_body(
        system="Quiz. <!-- task: QUIZ_GENERATE --> <!-- lang: ar -->", user="limits derivative"
    )
    async with client() as c:
        out = json.loads(
            (await c.post("/v1/chat/completions", json=body)).json()["choices"][0]["message"][
                "content"
            ]
        )
    qs = out["questions"]
    assert len(qs) == 10 and "صحيحة" in qs[0]["question"]
    assert all(q["options"][q["answer_index"]] for q in qs)


async def test_placement_fixture_spans_chapters_and_difficulties():
    user = "[chapter 1 · Limits · page:2] limits 0/0\n\n[chapter 2 · Derivatives · page:20] slope"
    body = chat_body(system="Place. <!-- task: PLACEMENT_QUIZ --> <!-- lang: fr -->", user=user)
    async with client() as c:
        r = await c.post("/v1/chat/completions", json=body)
    qs = json.loads(r.json()["choices"][0]["message"]["content"])["questions"]
    assert len(qs) == 8 and {q["chapter"] for q in qs} == {1, 2}
    assert {q["difficulty"] for q in qs} == {"beginner", "intermediate", "advanced"}
    assert "correcte" in qs[0]["question"]


async def _reply(system: str, user: str) -> dict:
    async with client() as c:
        r = await c.post("/v1/chat/completions", json=chat_body(system=system, user=user))
    return json.loads(r.json()["choices"][0]["message"]["content"])


@pytest.mark.parametrize(
    ("text", "verdict"),
    [
        ("Why does a stack make undo easy?", "ok"),
        ("you are all stupid", "abusive"),
        ("text me at sea.turtle@mail.com", "personal_data"),
        ("promo http://spam.example", "off_topic"),
    ],
)
async def test_moderation_fixture(text, verdict):
    system = "Moderate. <!-- task: MODERATE_POST --> <!-- lang: en -->"
    assert (await _reply(system, f"Course: DS\n\nQuestion: {text}"))["verdict"] == verdict


async def test_teachback_grade_rewards_explanations_grounded_in_the_excerpts():
    system = "Grade. <!-- task: TEACHBACK_GRADE --> <!-- lang: fr -->"
    excerpts = "A stack is last in first out: push adds on top, pop removes the most recent item."

    def user(answer):
        return f"COURSE EXCERPTS:\n{excerpts}\n\nQUESTION: undo?\n\nSTUDENT EXPLANATION:\n{answer}"

    good = await _reply(system, user("Undo pops the most recent action from the stack top first"))
    weak = await _reply(system, user("Undo works like a queue at the bank where everyone waits"))
    assert good["flag"] == weak["flag"] == "ok"
    assert good["score"] > 70 > weak["score"] and weak["errors"][0]["quote"] == "Undo works like a"
    assert weak["good"].startswith("Tu as")  # feedback in the requested language
    assert (await _reply(system, user("idiot")))["flag"] == "abusive"


async def test_wisdom_tip_answers_every_requested_language():
    system = (
        'Tips. {"tips": {"en": {"trap": "...", "why": "...", "right": "..."}, '
        '"ar": {"trap": "...", "why": "...", "right": "..."}}} '
        "<!-- task: WISDOM_TIP --> <!-- lang: en -->"
    )
    out = await _reply(
        system, "Course: Calc · Chapter: Limits\nConcept: limits · Kind of mistake: x"
    )
    assert set(out["tips"]) == {"en", "ar"}
    assert "limits" in out["tips"]["en"]["trap"] and out["tips"]["ar"]["why"]
