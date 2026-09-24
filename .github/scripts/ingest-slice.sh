#!/usr/bin/env bash
# The golden documents plus distractors, in the corpus's own format. The
# catalog and the citation graph are loaded at startup, so the app restarts
# afterwards to see what was just indexed.
set -euo pipefail
docker compose cp backend/eval/fixtures/corpus_slice.json app:/tmp/corpus_slice.json
docker compose exec -T app python -m app.corpus.ingest /tmp/corpus_slice.json
docker compose exec -T app python -m app.graph.build
docker compose restart app
"$(dirname "$0")/wait-for-api.sh"
curl -sf http://localhost:8010/catalog > /dev/null
