"""Audit OPT-26 (F-API-1): Postgres text can't hold a NUL byte, and nothing stripped it, so a
"\\u0000" in any free-text field (world name, Tutor message, arena post …) reached the database
and crashed the request with a 500. NULs are now removed from JSON bodies before validation."""

from tests.test_rag_indexing import gw, rag_env  # noqa: F401  (fixtures)
from tests.test_worlds_api import SEA, api  # noqa: F401  (fixtures)


async def test_a_nul_byte_in_free_text_is_dropped_not_a_500(api):  # noqa: F811
    r = await api.post("/api/worlds", json={"name": "Engi\u0000neering 2B"}, headers=SEA)
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "Engineering 2B"
    tutor = await api.post(
        "/api/tutor/00000000-0000-0000-0000-000000000000/turn",
        headers=SEA,
        json={"action": "message", "text": "\u0000"},
    )
    assert tutor.status_code == 404  # validated like any other request, not a crash


async def test_an_escaped_backslash_u_is_left_alone(api):  # noqa: F811
    r = await api.post("/api/worlds", json={"name": "C:\\u0000 notes"}, headers=SEA)
    assert r.status_code == 201 and r.json()["name"] == "C:\\u0000 notes"
