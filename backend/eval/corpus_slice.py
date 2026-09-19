"""Cut the CI slice of the corpus: every golden document plus distractors.

    uv run python eval/corpus_slice.py ../corpus/all_chunks.json

CI has no corpus - it is 75MB and lives outside the repo - so the eval indexes
this slice instead. Same row format as the full corpus, so the same ingest CLI
loads it. Distractors are what make retrieval able to fail: with only the
golden documents indexed, every query would find its source by default and
recall would read 100% no matter how retrieval was configured.
"""

import argparse
import json
import random
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent

# Distractor documents longer than this are skipped to keep the slice small
# enough to commit.
MAX_WINDOWS = 120


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--dataset", type=Path, default=EVAL_DIR / "golden_dataset.jsonl")
    parser.add_argument("--distractors", type=int, default=80)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=EVAL_DIR / "fixtures" / "corpus_slice.json")
    args = parser.parse_args(argv)

    rows = json.loads(args.corpus.read_text())
    golden_urls = {
        json.loads(line)["source"] for line in args.dataset.read_text().splitlines() if line.strip()
    }

    windows_per_url: dict[str, int] = {}
    for row in rows:
        windows_per_url[row["metadata"]["url"]] = row["metadata"]["total_chunks"]
    candidates = sorted(
        url for url, n in windows_per_url.items() if url not in golden_urls and n <= MAX_WINDOWS
    )
    keep = golden_urls | set(random.Random(args.seed).sample(candidates, args.distractors))

    slice_rows = [row for row in rows if row["metadata"]["url"] in keep]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(slice_rows, ensure_ascii=False))
    size_mb = args.output.stat().st_size / 1e6
    print(
        f"{len(keep)} documents ({len(golden_urls)} golden + {args.distractors} distractors), "
        f"{len(slice_rows)} rows, {size_mb:.1f} MB -> {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
