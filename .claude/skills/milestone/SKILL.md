---
name: milestone
description: Start work on the next milestone from docs/BUILD_PLAN.md (/milestone or /milestone M3). Loads the right docs, plans, and splits the work.
---

# Start a milestone

1. Read `docs/BUILD_PLAN.md`; pick the argument's milestone, or the first one with unticked boxes.
2. Read only the docs it needs (PLATFORM + ARCHITECTURE for M0–M2; PRODUCT section + DESIGN for
   screens; ECONOMY for M5) and `docs/DECISIONS.md` OPEN items that block it.
3. Enter plan mode. Produce: files to create/change, data model changes (Alembic), API endpoints,
   TaskKinds (follow the `ai-feature` skill), screens (follow `ui-screen`), tests, and the order.
   Flag anything that is blocked by an OPEN decision and propose a default.
4. After approval, implement in small commits (one concern each, conventional commit messages).
   Independent pieces (e.g. backend endpoint vs. frontend screen) can go to subagents in parallel;
   keep the gateway and economy in the main thread.
5. Finish with the `verify` skill and update the checkboxes.
