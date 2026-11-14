"""Audit OPT-08: PLATFORM.md asks for the four official orchestration names in logs and the
report, but nine internal labels (batch, extraction, guard, summary, classification,
generate-once, rewriting, repair, triage) reached ai_call_log.pattern and the admin Stats.

Now every logged pattern starts with an official name (escalation, draft-then-revise, plan-once /
execute-compact, narrow-before-generating), the error contract's `fallback`, or `none`; the
internal step stays as a sub-label after a colon (`none:guard`). Stats groups calls by the
official name, rows logged before this change included."""

from sqlalchemy import select

from app.gateway import Task, TaskKind
from app.gateway.router import OFFICIAL, ROUTES, official
from app.models import AICallLog
from tests.admin_helpers import READ, enable_admin
from tests.test_admin_phase_a import MESSAGES, api, gateway  # noqa: F401  (fixture)


def test_every_route_logs_an_official_name():
    for kind, route in ROUTES.items():
        assert official(route.pattern) in OFFICIAL, (kind, route.pattern)
    unofficial = {r.pattern.split(":", 1)[1] for r in ROUTES.values() if ":" in r.pattern}
    assert unofficial >= {"triage", "batch", "extraction", "summary", "guard", "classification"}
    assert official("guard") == "none" and official("forced-fallback") == "fallback"  # old rows


async def test_the_call_log_and_stats_carry_the_official_names(api, sm, mock_llm, monkeypatch):  # noqa: F811
    enable_admin(monkeypatch)
    gw = gateway(sm, mock_llm)
    for kind in (TaskKind.TUTOR_GUARD, TaskKind.MODERATE_POST, TaskKind.NOTES_WRITE):
        await gw.run(Task(kind=kind, lane="interactive", messages=MESSAGES, response_format="text"))
    async with sm() as s:
        s.add(
            AICallLog(
                task_kind="TUTOR_SUMMARY",
                model_tier="compact",
                provider="mock",
                model="m",
                pattern="summary",
                status_code=200,
            )
        )  # a pre-OPT-08 row
        await s.commit()
        logged = set(await s.scalars(select(AICallLog.pattern)))
    assert {"none:guard", "none:classification", "plan-once", "summary"} <= logged
    stats = (await api.get("/api/admin/stats", params={"provider": "mock"}, headers=READ)).json()
    assert stats["by_pattern"] == {"none": 3, "plan-once / execute-compact": 1}
