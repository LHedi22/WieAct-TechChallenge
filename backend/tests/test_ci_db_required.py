"""Audit OPT-29 (F-TEST-1): with Postgres unreachable the DB tests used to skip, so a CI run could
go green while testing almost nothing. In CI (CI=true, set by GitHub Actions) that is a failure."""

import pytest

from tests.db import unreachable


def test_ci_fails_when_postgres_is_unreachable(monkeypatch):
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception, match="Postgres"):
        unreachable()


def test_a_laptop_without_postgres_still_skips(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(pytest.skip.Exception):
        unreachable()
