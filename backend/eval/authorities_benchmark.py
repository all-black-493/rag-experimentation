"""Does the case analysis find the law a matter's documents cite, and resolve it?

    uv run python eval/authorities_benchmark.py          # against a running API

Uploads the matter fixtures, runs the case-analysis workflow, and scores the
deterministic step against `golden_authorities.jsonl`: every citation the
documents make, found or not; resolved against the corpus when the corpus
holds it, and left unresolved when it doesn't. No judge, seconds to run.
"""

import json
import time
from pathlib import Path

import httpx

EVAL_DIR = Path(__file__).resolve().parent
GOLDEN = EVAL_DIR / "golden_authorities.jsonl"


def main(api_url: str = "http://localhost:8010") -> int:
    from retrieval_benchmark import prepare_matter

    expected = {
        (c["kind"], c["key"].lower()): c["in_corpus"]
        for line in GOLDEN.read_text().splitlines()
        if line.strip()
        for c in json.loads(line)["cites"]
    }
    matter_id = prepare_matter(api_url)
    try:
        with httpx.Client(base_url=api_url, timeout=300.0) as client:
            started = time.time()
            job = client.post("/workflows/case-analysis", json={"matter_id": matter_id})
            job.raise_for_status()
            job_id = job.json()["job_id"]
            while True:
                status = client.get(f"/workflows/{job_id}").json()
                if status["done"]:
                    break
                time.sleep(1)
            elapsed = time.time() - started
            analysis = client.get(f"/matters/{matter_id}").json()["analysis"]
    finally:
        httpx.delete(f"{api_url}/matters/{matter_id}", timeout=60.0)

    found = {(a["kind"], a["key"].lower()): a for a in analysis["authorities"]}
    hits = [k for k in expected if k in found]
    spurious = [k for k in found if k not in expected]
    resolved_right = [
        k for k in hits if (found[k]["doc_id"] is not None) == expected[k]
    ]
    anchored = [k for k in hits if found[k]["sources"]]
    print(
        f"authorities   found {len(hits)}/{len(expected)}   spurious {len(spurious)}   "
        f"resolution right {len(resolved_right)}/{len(hits)}   anchored {len(anchored)}/{len(hits)}   "
        f"wall {elapsed:.1f}s   warnings {len(analysis['warnings'])}"
    )
    for a in found.values():
        print(f"  {a['ref']:<32} {a['title'] or '-':<24} applied by {a['applied_by']:>3}  sources {a['sources']}")
    return 0 if len(hits) == len(expected) and not spurious else 1


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(EVAL_DIR))
    raise SystemExit(main(*sys.argv[1:]))
