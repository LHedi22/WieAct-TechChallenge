"""Audit OPT-20 (CA-4): task kinds in the routing table that no code calls. TRANSLATE_SHORT is now
the chapter glossary (OPT-11); the rest are marked reserved, so the table shows what really runs."""

import re
from pathlib import Path

from app.gateway import TaskKind
from app.gateway.router import RESERVED, ROUTES

APP = Path(__file__).resolve().parents[1] / "app"
SKIP = {APP / "gateway" / "router.py", APP / "gateway" / "types.py"}


def used_kinds() -> set[str]:
    found: set[str] = set()
    for path in APP.rglob("*.py"):
        if path not in SKIP:
            found |= set(re.findall(r"TaskKind\.([A-Z_]+)", path.read_text(encoding="utf-8")))
    return found


def test_every_routed_kind_is_used_or_reserved():
    used = used_kinds()
    unused = {k.value for k in ROUTES if k.value not in used}
    assert unused == {k.value for k in RESERVED}


def test_reserved_kinds_are_named_in_the_architecture_table():
    table = (APP.parents[1] / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    for kind in RESERVED:
        row = next(line for line in table.splitlines() if line.startswith(f"| {kind.value}"))
        assert "reserved" in row.lower(), row
    assert TaskKind.TRANSLATE_SHORT not in RESERVED
