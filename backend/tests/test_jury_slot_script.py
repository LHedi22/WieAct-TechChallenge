"""Audit OPT-03: scripts/jury_slot.py prints the jury-slot plan and runs nothing without --cloud.
These tests never run a step: the subprocess runner is a fake."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "scripts").exists():  # the backend container mounts scripts/ at /scripts
    ROOT = Path("/")
spec = importlib.util.spec_from_file_location("jury_slot", ROOT / "scripts" / "jury_slot.py")
script = importlib.util.module_from_spec(spec)
sys.modules["jury_slot"] = script  # @dataclass looks its module up
spec.loader.exec_module(script)


def never(*a, **k):
    raise AssertionError("nothing may run")


def test_without_cloud_it_only_prints_the_plan(capsys):
    assert script.main([], ask=never, run=never) == 0
    out = capsys.readouterr().out
    assert "Dry run: nothing was sent" in out and "2g" in out


def test_cloud_needs_a_real_api_and_chapter(capsys):
    assert script.main(["--cloud"], ask=never, run=never) == 2


def test_every_platform_eval_asks_for_cloud_itself():
    for step in script.plan("https://api", "ch"):
        if "app.evals" in step.command and "quiz " not in step.command:
            assert "--cloud" in step.command, step.key


def test_with_cloud_each_step_is_confirmed_and_a_no_skips_it():
    answers = iter(["n"] * 20)
    ran: list[list[str]] = []
    code = script.main(
        ["--cloud", "--api", "https://api", "--chapter", "ch", "--from", "2a"],
        ask=lambda _: next(answers),
        run=lambda cmd: ran.append(cmd) or 0,
    )
    assert code == 0 and ran == []


def test_the_runbook_and_the_script_list_the_same_steps():
    runbook = (ROOT / "docs" / "report" / "JURY_SLOT_RUNBOOK.md").read_text(encoding="utf-8")
    for step in script.plan("x", "y"):
        assert f"| {step.key} |" in runbook, step.key
