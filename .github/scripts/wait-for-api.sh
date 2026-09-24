#!/usr/bin/env bash
# Block until the API answers, or give up and say what the container said.
set -euo pipefail
for _ in $(seq 1 90); do
  if curl -sf http://localhost:8010/health; then
    echo
    exit 0
  fi
  sleep 2
done
echo "API did not become healthy in time" >&2
docker compose logs --no-color >&2
exit 1
