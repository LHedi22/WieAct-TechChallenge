#!/usr/bin/env bash
# Rebuild docs/report/video/final.mp4 and final-subtitled.mp4 from the raw clips (see edit.py).
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=${PYTHON:-C:/Python311/python.exe}
[ -f docs/report/video/vo/lines.txt ] || "$PY" scripts/video/voiceover.py
"$PY" scripts/video/edit.py
