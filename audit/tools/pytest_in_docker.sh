#!/bin/sh
# Run backend pytest inside the lw-audit backend image with the repo mounts the tests need.
# Usage (Git Bash, repo root): sh audit/tools/pytest_in_docker.sh [pytest args]
W=$(pwd -W 2>/dev/null || pwd)
MSYS_NO_PATHCONV=1 docker compose -p lw-audit -f docker-compose.yml -f audit/compose/mock.yml run --rm -T --no-deps \
  -v "$W/mock-llm:/mock-llm:ro" -v "$W/scripts:/scripts:ro" -v "$W/docs:/docs:ro" -v "$W/design:/design:ro" \
  -v "$W/.env.example:/.env.example:ro" -v "$W/docker-compose.yml:/docker-compose.yml:ro" \
  backend uv run pytest -p no:cacheprovider "$@" 2>&1 | grep -v -E "level=warning|Container lw-audit"
