"""The in-slot run's guards: never on the cloud without --cloud, never in production, and no
repeated identical Teach-Back requests on a second run."""

import json

import httpx

from app.evals import slot


def status(provider: str, app_env: str = "development") -> httpx.MockTransport:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/system/status":
            body = {"provider": provider, "app_env": app_env, "offline_demo_mode": False}
            return httpx.Response(200, json=body)
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    transport.calls = calls  # type: ignore[attr-defined]
    return transport


async def run_with(transport, monkeypatch, **kw) -> int:
    real = httpx.AsyncClient
    monkeypatch.setattr(slot.httpx, "AsyncClient", lambda **a: real(transport=transport, **a))
    args = dict(code="OLIVE-7Q2", course="Data Structures", level="advanced", langs=["en"])
    return await slot.run("http://api", timeout_s=1, **args, **kw)


async def test_refuses_the_cloud_without_the_flag(monkeypatch):
    t = status("cloud")
    assert await run_with(t, monkeypatch, cloud=False) == 1
    assert t.calls == ["/api/system/status"]  # nothing started


async def test_refuses_production(monkeypatch):
    t = status("cloud", app_env="production")
    assert await run_with(t, monkeypatch, cloud=True) == 1
    assert t.calls == ["/api/system/status"]


def test_saved_grades_are_reused_only_when_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(slot, "OUT", tmp_path)
    assert slot._graded_before("cloud", "fr") is None
    path = tmp_path / "cloud-teachback_solo-fr.json"
    answers = [{"job": {"status": "done"}}, {"job": {"status": "failed"}}]
    path.write_text(json.dumps({"output": {"answers": answers}}), encoding="utf-8")
    assert slot._graded_before("cloud", "fr") is None  # a failed grade is sent again
    answers[1]["job"]["status"] = "done"
    path.write_text(json.dumps({"output": {"answers": answers}}), encoding="utf-8")
    assert slot._graded_before("cloud", "fr")["reused"] is True
    assert slot._graded_before("mock", "fr") is None  # per provider


def test_delta_counts_only_this_run():
    before = {"calls": 10, "by_tier": {"mid": {"calls": 4}}, "refusals": {"saturated": 1}}
    after = {
        "calls": 13,
        "by_tier": {"mid": {"calls": 5}, "compact": {"calls": 2}},
        "refusals": {"saturated": 1, "quota": 2},
        "repeated_identical": 0,
    }
    line = slot._delta(before, after)
    assert "calls 3" in line and "mid 1" in line and "compact 2" in line and "refusals 2" in line
