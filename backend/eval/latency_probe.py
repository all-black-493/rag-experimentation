"""One question, timed at every event of the stream, as the reader experiences it.

    uv run python eval/latency_probe.py "What is the penalty for ...?" --mode ask
    uv run python eval/latency_probe.py --mode research "Is a probationary employee ...?"

Prints the seconds from the request to each event: plan, sources, first token,
done, verdict - the same points the README's latency baseline was measured at.
A research question is started as a run and followed. The question should be
one the caches haven't seen, or the plan and retrieval come back in no time.
"""

import argparse
import json
import sys
import time

import httpx


def events(client: httpx.Client, mode: str, question: str, matter_id: str | None):
    body = {"question": question, "mode": mode, "matter_id": matter_id}
    if mode == "research":
        job = client.post("/workflows/research", json=body)
        job.raise_for_status()
        stream = client.stream("GET", f"/workflows/{job.json()['job_id']}/events")
    else:
        stream = client.stream("POST", "/query/stream", json=body)
    with stream as response:
        response.raise_for_status()
        current = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                current = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and current:
                yield current, line.split(":", 1)[1].strip()
                current = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--mode", choices=["ask", "research", "search"], default="ask")
    parser.add_argument("--matter-id")
    parser.add_argument("--api-url", default="http://localhost:8010")
    args = parser.parse_args()

    marks: dict[str, float] = {}
    started = time.monotonic()
    tokens = 0
    with httpx.Client(base_url=args.api_url, timeout=1800.0) as client:
        for event, data in events(client, args.mode, args.question, args.matter_id):
            now = time.monotonic() - started
            if event == "token":
                tokens += 1
                marks.setdefault("first token", now)
                marks["last token"] = now
            elif event == "review":
                marks[f"review {json.loads(data).get('round')}"] = now
            else:
                marks.setdefault(event, now)
            if event == "error":
                print(f"error: {data}", file=sys.stderr)
        health = client.get("/health").json()
    print(f"{health.get('provider', '?')}: {health.get('models', '?')}")
    for name, seconds in marks.items():
        print(f"{name:<14} {seconds:7.1f} s")
    print(f"{'tokens':<14} {tokens:7d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
