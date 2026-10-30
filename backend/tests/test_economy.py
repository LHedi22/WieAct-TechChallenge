"""The economy constants (ECONOMY.md) and the public economy endpoint."""

from datetime import UTC, datetime

from app.api.economy import EconomyOut
from app.core import economy
from tests.test_auth import SIGNUP, api  # noqa: F401  (fixture)


def test_numbers_match_economy_md():
    assert economy.DAILY_FREE_COINS == 20 and economy.DAILY_EARN_CAP == 10
    assert economy.COST["quiz"] == 5 and economy.COST["tutor_session"] == 8
    assert economy.COST["placement_quiz"] == 0 and economy.COST["generate_shared_asset"] == 15
    assert economy.EARN["daily_challenge"] == 3 and economy.EARN["peer_answer_good"] == 3
    assert economy.BUILDINGS["socratic_tutor"]["cost"] == 8  # mockup said 3 (DESIGN.md fix 2)
    assert economy.EXAM_PASS_DAILY_LIMIT == 15


def test_refill_is_next_tunis_midnight():
    # 22:30 UTC on 29/10 is 23:30 in Tunis (UTC+1) → refill at 00:00 Tunis = 23:00 UTC
    assert economy.next_refill(datetime(2026, 10, 29, 22, 30, tzinfo=UTC)) == datetime(
        2026, 10, 29, 23, 0, tzinfo=UTC
    )
    assert economy.next_refill(datetime(2026, 10, 29, 23, 30, tzinfo=UTC)) == datetime(
        2026, 10, 30, 23, 0, tzinfo=UTC
    )


async def test_economy_endpoint_is_public_and_wallet_needs_sign_in(api):  # noqa: F811
    eco = (await api.get("/api/economy")).json()
    assert eco == EconomyOut.model_validate(economy.as_dict()).model_dump(mode="json")
    assert eco["buildings"]["quiz_hall"]["cost"] == economy.COST["quiz"]
    assert (await api.get("/api/wallet")).status_code == 401
    await api.post("/api/auth/signup", json=SIGNUP)
    wallet = (await api.get("/api/wallet")).json()
    assert wallet["coins"] == economy.DAILY_FREE_COINS and wallet["points"] == 0
