"""Style test scoring (no AI) and the profile."""

from app.features.onboarding.router import style_mix, suggestions
from tests.test_auth import SIGNUP, api  # noqa: F401  (fixture)


def test_style_mix_sums_to_100_and_nobody_is_zero():
    mix = style_mix(["visual", "visual", "practice", "visual"])
    assert sum(mix.values()) == 100 and min(mix.values()) > 0
    assert mix["visual"] > mix["practice"] > max(mix["listening"], mix["teaching"])
    assert abs(mix["listening"] - mix["teaching"]) <= 1  # 12.5 + 12.5: one rounds up
    assert style_mix(["teaching"] * 4)["teaching"] == 63  # 5/8
    even = style_mix(["visual", "practice", "listening", "teaching"])
    assert set(even.values()) == {25}


def test_suggestions_follow_the_top_two_styles():
    mix = style_mix(["visual", "practice", "visual", "practice"])
    assert suggestions(mix) == ["study_studio", "quiz_hall"]  # mockup 03


async def test_style_and_profile_roundtrip(api):  # noqa: F811
    await api.post("/api/auth/signup", json=SIGNUP)
    r = await api.post("/api/onboarding/style", json={"answers": ["visual", "practice", "visual"]})
    assert r.json()["top"] == ["visual", "practice"]
    assert r.json()["suggested_buildings"] == ["study_studio", "quiz_hall"]
    put = await api.put(
        "/api/profile",
        json={
            "field": " Engineering ",
            "year": 2,
            "languages": ["fr", "ar"],
            "daily_minutes": 45,
            "reminder_time": "18:30",
            "goal": "deep",
            "avatar": {"skin": "s2", "outfit": "o1", "extra": "cap"},
            "finish": True,
        },
    )
    p = put.json()
    assert p["field"] == "Engineering" and p["mix"]["visual"] > p["mix"]["teaching"]
    assert p["avatar"] == {"skin": "s2", "outfit": "o1", "extra": "cap"} and p["onboarded"]
    me = (await api.get("/api/auth/me")).json()
    assert me["onboarded"] and me["avatar"]["extra"] == "cap"


async def test_locked_cosmetic_and_bad_avatar(api):  # noqa: F811
    await api.post("/api/auth/signup", json=SIGNUP)
    locked = await api.put(
        "/api/profile", json={"avatar": {"skin": "s1", "outfit": "o1", "extra": "chechia"}}
    )
    assert locked.status_code == 403 and locked.json()["detail"] == "errors.cosmetic_locked"
    bad = await api.put("/api/profile", json={"avatar": {"skin": "zz", "outfit": "o1"}})
    assert bad.status_code == 400
    bad_hair = {"skin": "s1", "outfit": "o1", "hair": "mohawk"}
    assert (await api.put("/api/profile", json={"avatar": bad_hair})).status_code == 400


async def test_avatar_keeps_hair(api):  # noqa: F811
    await api.post("/api/auth/signup", json=SIGNUP)
    look = {"skin": "s3", "outfit": "o4", "hair": "wrap", "hair_color": "c2", "extra": "glasses"}
    p = (await api.put("/api/profile", json={"avatar": look})).json()
    assert p["avatar"] == look


async def test_skip_still_finishes_onboarding(api):  # noqa: F811
    await api.post("/api/auth/signup", json=SIGNUP)
    p = (await api.put("/api/profile", json={"finish": True})).json()
    assert p["onboarded"] and p["mix"] == {
        "visual": 25,
        "practice": 25,
        "listening": 25,
        "teaching": 25,
    }
