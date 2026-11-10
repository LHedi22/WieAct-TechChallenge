#!/usr/bin/env bash
# Contact sheet of a clip: one frame every N seconds (default 1), 6 per row, labelled with time.
# Usage: scripts/video/contact.sh <clip> <out.png> [every_s]
set -euo pipefail
clip=$1; out=$2; every=${3:-1}
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$clip" 2>/dev/null || echo 0)
n=$(python -c "import math,sys; print(max(1, math.ceil(float('${dur}' or 0)/${every})))")
rows=$(( (n + 5) / 6 ))
ffmpeg -v error -y -i "$clip" -vf "fps=1/${every},scale=480:-2,drawtext=text='%{pts\:hms}':x=6:y=6:fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.6,tile=6x${rows}" -frames:v 1 "$out"
echo "$out ($n frames, ${dur}s)"
