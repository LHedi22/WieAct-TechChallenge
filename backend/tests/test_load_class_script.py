"""Audit OPT-30 (F-LOAD-1): load.py needs the mock's /_mock and the dev demo-jobs endpoint, so the
"load test against cloud" box could never run. scripts/load_class.py uses real features only and
refuses a cloud backend unless --cloud is given, before any sign-up."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "scripts").exists():  # the backend container mounts scripts/ at /scripts
    ROOT = Path("/")
spec = importlib.util.spec_from_file_location("load_class", ROOT / "scripts" / "load_class.py")
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def test_a_cloud_backend_needs_the_explicit_flag():
    assert script.refuse("cloud", cloud=False)
    assert script.refuse("cloud", cloud=True) is None
    assert script.refuse("mock", cloud=False) is None


def test_it_uses_real_features_only():
    source = (ROOT / "scripts" / "load_class.py").read_text(encoding="utf-8")
    assert "/_mock" not in source and "/api/dev/" not in source and "X-Dev-User" not in source


def test_the_summary_counts_sharing_coins_and_waits():
    rows = [
        {"http": 200, "cost": 15, "job": "j1", "status": "done", "wait_s": 10.0, "max_pos": 2},
        {"http": 200, "cost": 0, "job": "j1", "status": "done", "wait_s": 12.0, "quick": True},
        {"http": 402, "cost": None, "job": None, "wait_s": 0.1},
    ]
    out = script.summarize("studio", rows, {"calls": 5, "mid": 1}, {"calls": 8, "mid": 2})
    assert out["distinct_jobs"] == 1 and out["coins_charged"] == 15
    assert out["http"] == [200, 402] and out["quick_mode"] == 1 and out["max_queue_position"] == 2
    assert out["stats_delta"] == {"calls": 3, "mid": 1}
    assert out["wait_p50_s"] == 10.0


async def test_it_refuses_before_any_sign_up(monkeypatch, capsys):
    seen: list[str] = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, path, **k):
            seen.append(path)
            return type("R", (), {"json": lambda self: {"provider": "cloud"}})()

        async def post(self, path, **k):  # pragma: no cover - must never run
            seen.append(path)
            raise AssertionError("no request may follow a refusal")

    monkeypatch.setattr(script.httpx, "AsyncClient", Fake)
    code = await script.main(["--code", "X", "--chapter", "c"])
    assert code == 2 and seen == ["/api/health"]
    assert "--cloud" in capsys.readouterr().err


@pytest.mark.parametrize("phase", ["studio", "quiz", "tutor"])
def test_each_phase_maps_to_its_start_route(phase):
    path, body = script.PHASES[phase]("ch1", "advanced")
    assert path.startswith("/api/") and body["level"] == "advanced"
