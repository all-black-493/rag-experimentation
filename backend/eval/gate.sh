#!/usr/bin/env bash
# The faithfulness gate against the local stack, detached so it outlives the
# shell and resumable after a restart: each result lands in
# report.partial.jsonl as it is scored; run this again to continue.
cd "$(dirname "$0")" || exit 1
export PYTHONUNBUFFERED=1
nohup setsid uv run python run_eval.py --concurrency 1 --timeout 2700 --resume >> gate.log 2>&1 < /dev/null &
disown
sleep 3
pgrep -af "[.]venv/bin/python3 run_eval" || echo "did not start; see gate.log"
