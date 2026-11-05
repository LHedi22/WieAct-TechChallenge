"""Audit F-RES-2 (Tier 2 #11): an interactive mid call that timed out was retried as `transient`
with the full 90 s timeout each time and never fell back to compact; a student watched "Connection
hiccup" for 5 minutes for one Study pack, and the platform saw the identical request 3 times.

Now an interactive mid call gets a shorter budget (LLM_INTERACTIVE_MID_TIMEOUT_S) and, on timeout,
falls back to compact at once (Quick mode) without repeating the mid request. Background work keeps
the long budget and is deferred as before."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.gateway import Defer, Task, TaskKind
from app.gateway.client import LLMClient
from app.gateway.limiter import Limiter
from app.gateway.service import Gateway
from tests.conftest import FAST_MOCK, MockConfig, create_mock_app

MESSAGES = [
    {"role": "system", "content": "Write the revision notes."},
    {"role": "user", "content": "Limits"},
]


class SlowMid(httpx.AsyncBaseTransport):
    """Forwards to the in-process mock, except that every mid-model chat call times out."""

    def __init__(self, app) -> None:
        self.inner = httpx.ASGITransport(app=app)
        self.calls: list[tuple[str, float | None]] = []  # (model, read timeout the call carried)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            model = json.loads(request.content)["model"]
            self.calls.append((model, (request.extensions.get("timeout") or {}).get("read")))
            if model == "mock-mid":
                raise httpx.ReadTimeout("mid took too long", request=request)
        return await self.inner.handle_async_request(request)


@pytest.fixture
def setup(sm, monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_S", "90")
    monkeypatch.setenv("LLM_INTERACTIVE_MID_TIMEOUT_S", "45")
    settings = Settings()
    transport = SlowMid(create_mock_app(MockConfig(**FAST_MOCK), seed=7))

    async def no_sleep(_s: float) -> None:
        return None

    gw = Gateway(
        settings,
        sm,
        client_factory=lambda p: LLMClient(
            p,
            timeout_s=settings.LLM_TIMEOUT_S,
            disable_thinking=True,
            http_client=httpx.AsyncClient(transport=transport),
        ),
        sleep=no_sleep,
        limiter=Limiter(6000, 2, burst=50),
    )
    return gw, transport


async def test_interactive_mid_timeout_falls_back_to_compact_at_once(setup):
    gw, transport = setup
    res = await gw.run(Task(kind=TaskKind.NOTES_WRITE, lane="interactive", messages=MESSAGES))
    assert res.quick_mode and res.model_tier == "compact"
    mids = [c for c in transport.calls if c[0] == "mock-mid"]
    assert len(mids) == 1  # the identical mid request is not sent again
    assert mids[0][1] == 45  # with the short interactive budget, not 90 s


async def test_background_mid_timeout_keeps_the_long_budget_and_is_deferred(setup):
    gw, transport = setup
    with pytest.raises(Defer) as e:
        await gw.run(Task(kind=TaskKind.NOTES_WRITE, lane="background", messages=MESSAGES))
    assert e.value.reason == "transient"
    mids = [c for c in transport.calls if c[0] == "mock-mid"]
    assert mids and all(timeout == 90 for _, timeout in mids)
    assert not [c for c in transport.calls if c[0] == "mock-compact"]  # no fallback in background
