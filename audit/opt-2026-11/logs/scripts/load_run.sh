#!/bin/sh
# usage: load_run.sh <name> <load.py args...>
name=$1; shift
LOG=/Users/mac/WieAct-TechChallenge/audit/opt-2026-11/logs
JL=/tmp/cc-opt/logs/llm-calls-mock.jsonl
start=$(wc -l < $JL 2>/dev/null || echo 0)
echo "start_line=$start" > $LOG/$name.meta
date -u +%FT%TZ >> $LOG/$name.meta
/tmp/cc-opt/dc run --rm -T --no-deps -v "/Users/mac/WieAct-TechChallenge/scripts:/scripts:ro" backend \
  uv run python /scripts/load.py --api http://backend:8000 --mock http://mock-llm:9000 "$@" > $LOG/$name.log 2>&1
echo "exit=$?" >> $LOG/$name.meta
echo "end_line=$(wc -l < $JL)" >> $LOG/$name.meta
date -u +%FT%TZ >> $LOG/$name.meta
