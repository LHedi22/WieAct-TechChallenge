---
name: fix-bug
description: Fix one bug from report to commit — /fix-bug <AUDIT.md finding ID | debug bundle path | description>. Reproduces it with a failing test first, smallest fix, verify, one commit, marks the finding fixed. Runs the bug-fixer agent.
---

# Fix a bug

Input: `$ARGUMENTS` — an `AUDIT.md` finding ID (`N-4`, `F-QUIZ-1` …), a bundle path
(`debug/bundles/bundle-job-….md`) or a plain description.

1. If the input is empty, list the open findings in `docs/report/AUDIT.md` (rows not marked fixed,
   residuals in the latest addendum) and ask which one.
2. If the input is a description of a job or student problem and no bundle exists, suggest
   `ADMIN_TOKEN=… python3 scripts/debug_bundle.py --job <id> --logs compose` first (the human runs
   it if `ADMIN_TOKEN` isn't in the shell; never read it from `.env`).
3. Start the `bug-fixer` agent with the input and these reminders: no cloud calls, no `.env`,
   reproduce with a failing test before fixing, one bug per commit
   `fix(<area>): <title> [<ID>]`, mark it fixed in AUDIT.md, a DECISIONS.md line if behaviour
   changed, say so explicitly if a prompt in `backend/app/prompts/` was edited (then run the prompt
   eval on mock).
4. Relay its report: root cause, failing test, fix, commit hash, suites run. If it could not
   reproduce, relay what it tried and the evidence it asks for. Don't push.
