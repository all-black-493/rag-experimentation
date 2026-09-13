"""Quality metrics over a time window, read back from the Langfuse Metrics API.

    uv run python -m app.metrics --follow          # live, one line per query
    uv run python -m app.metrics --since 7d
    uv run python -m app.metrics --day 2026-09-08
    uv run python -m app.metrics --since 14d --daily

Answers "what happened when quality degraded last Tuesday?" - point the window at
the day, compare against the days around it, then open the worst traces in
Langfuse from the ids printed at the end.
"""

import argparse
import base64
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Settings, get_settings

_METRICS_PATH = "/api/public/v2/metrics"
_OBSERVATIONS_PATH = "/api/public/v2/observations"
_TIMEOUT = 30.0

# Only the root span of each request: one row per query rather than per LLM call.
_ROOT_ONLY = [{"column": "isRootObservation", "operator": "=", "value": True, "type": "boolean"}]
_ROOT_SPAN_NAME = "rag-query"


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        return f"{self.start:%Y-%m-%d %H:%M} → {self.end:%Y-%m-%d %H:%M} UTC"


def _auth_header(settings: Settings) -> dict[str, str]:
    raw = f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def _query_metrics(settings: Settings, client: httpx.Client, query: dict) -> list[dict]:
    response = client.get(
        f"{settings.langfuse_base_url}{_METRICS_PATH}",
        params={"query": json.dumps(query)},
        headers=_auth_header(settings),
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def _observations_query(window: Window, metrics: list[dict], **extra) -> dict:
    return {
        "view": "observations",
        "metrics": metrics,
        "dimensions": [],
        "filters": _ROOT_ONLY,
        "fromTimestamp": window.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "toTimestamp": window.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        **extra,
    }


def _score_query(window: Window, name: str, view: str, aggregation: str) -> dict:
    return {
        "view": view,
        "metrics": [{"measure": "value", "aggregation": aggregation}],
        "dimensions": [],
        "filters": [{"column": "name", "operator": "=", "value": name, "type": "string"}],
        "fromTimestamp": window.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "toTimestamp": window.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _first(rows: list[dict], key: str) -> float | None:
    if not rows:
        return None
    value = rows[0].get(key)
    return float(value) if value is not None else None


def collect(settings: Settings, window: Window) -> dict:
    """One window's headline numbers."""
    with httpx.Client() as client:
        volume = _query_metrics(
            settings,
            client,
            _observations_query(window, [{"measure": "count", "aggregation": "count"}]),
        )
        latency = _query_metrics(
            settings,
            client,
            _observations_query(
                window,
                [
                    {"measure": "latency", "aggregation": "p50"},
                    {"measure": "latency", "aggregation": "p95"},
                ],
            ),
        )
        # Deliberately not root-only: cost is recorded on the generations, so a
        # root-filtered sum is always zero.
        cost = _query_metrics(
            settings,
            client,
            {
                "view": "observations",
                "metrics": [{"measure": "totalCost", "aggregation": "sum"}],
                "dimensions": [],
                "filters": [],
                "fromTimestamp": window.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "toTimestamp": window.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        # Averaging a boolean score gives the rate directly.
        scores = {
            name: _first(_query_metrics(settings, client, _score_query(window, name, view, agg)), key)
            for name, view, agg, key in (
                ("citation_coverage", "scores-numeric", "avg", "avg_value"),
                ("invalid_citations", "scores-numeric", "sum", "sum_value"),
                ("answered", "scores-boolean", "avg", "avg_value"),
                ("grounded", "scores-boolean", "avg", "avg_value"),
                ("failed", "scores-boolean", "avg", "avg_value"),
            )
        }

    requests = _first(volume, "count_count")
    cost_total = _first(cost, "sum_totalCost")
    return {
        "requests": requests,
        # The Metrics API reports latency in milliseconds (the observations API
        # reports seconds - don't mix them).
        "latency_p50_ms": _first(latency, "p50_latency"),
        "latency_p95_ms": _first(latency, "p95_latency"),
        "cost_total_usd": cost_total,
        "cost_per_request_usd": (
            cost_total / requests if cost_total is not None and requests else None
        ),
        **scores,
    }


def worst_traces(settings: Settings, window: Window, limit: int = 5) -> list[dict]:
    """Slowest requests in the window - where to start reading.

    Note the observations API reports `latency` in seconds, unlike the Metrics
    API's milliseconds.
    """
    with httpx.Client() as client:
        response = client.get(
            f"{settings.langfuse_base_url}{_OBSERVATIONS_PATH}",
            params={
                "fromStartTime": window.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "toStartTime": window.end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "fields": "core,basic,metrics",
                "limit": 100,
            },
            headers=_auth_header(settings),
            timeout=_TIMEOUT,
        )
        response.raise_for_status()

    roots = [
        o
        for o in response.json().get("data", [])
        if o.get("isRootObservation") and o.get("name") == _ROOT_SPAN_NAME
    ]
    roots.sort(key=lambda o: o.get("latency") or 0, reverse=True)
    return roots[:limit]


def follow(settings: Settings, interval: float = 3.0) -> int:
    """Print each query as it lands, newest last, until interrupted.

    Polling, not streaming: the Langfuse API is REST, with no subscription
    endpoint. Everything shown comes off the root observation itself - question,
    latency, citation count, grounded/declined - so there's no extra request per
    trace and no waiting on score ingestion.
    """
    seen: set[str] = set()
    cursor = datetime.now(UTC) - timedelta(minutes=2)
    # flush on every line: piped into anything (tee, grep) Python buffers stdout,
    # which would hold a live feed hostage until the buffer fills.
    print(f"Following {settings.langfuse_base_url} — Ctrl-C to stop\n", flush=True)

    with httpx.Client() as client:
        while True:
            response = client.get(
                f"{settings.langfuse_base_url}{_OBSERVATIONS_PATH}",
                params={
                    "fromStartTime": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "fields": "core,basic,io,metadata,metrics",
                    "limit": 50,
                },
                headers=_auth_header(settings),
                timeout=_TIMEOUT,
            )
            response.raise_for_status()

            fresh = [
                o
                for o in response.json().get("data", [])
                if o.get("name") == _ROOT_SPAN_NAME
                and o.get("isRootObservation")
                and o.get("id") not in seen
            ]
            for observation in sorted(fresh, key=lambda o: o.get("startTime") or ""):
                seen.add(observation["id"])
                print(_follow_line(observation), flush=True)

            time.sleep(interval)


def _follow_line(observation: dict) -> str:
    metadata = observation.get("metadata") or {}
    output = observation.get("output") or {}
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            output = {}
    question = (observation.get("input") or {})
    if isinstance(question, str):
        try:
            question = json.loads(question)
        except json.JSONDecodeError:
            question = {}

    citations = output.get("citations", 0)
    declined = metadata.get("declined")
    verdict = "DECLINED" if declined else ("ok" if metadata.get("grounded") else "UNGROUNDED")
    invalid = metadata.get("invalid_indices") or []

    return (
        f"{(observation.get('startTime') or '')[11:19]}  "
        f"{_fmt(observation.get('latency'), 's', 1):>7}  "
        f"{verdict:<10} {citations} cite{'' if citations == 1 else 's'}"
        f"{'  INVALID ' + str(invalid) if invalid else ''}  "
        f"{str(question.get('question', ''))[:60]}"
    )


def _fmt(value: float | None, suffix: str = "", decimals: int = 2) -> str:
    return "-" if value is None else f"{value:,.{decimals}f}{suffix}"


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def render(window: Window, stats: dict) -> str:
    requests = stats["requests"]
    lines = [
        f"Window   {window.label}",
        f"Requests {_fmt(requests, decimals=0)}",
        "",
        f"  latency p50          {_fmt(stats['latency_p50_ms'], ' ms', 0)}",
        f"  latency p95          {_fmt(stats['latency_p95_ms'], ' ms', 0)}",
        f"  cost / request       ${_fmt(stats['cost_per_request_usd'], '', 4)}",
        f"  cost total           ${_fmt(stats['cost_total_usd'], '', 4)}",
        "",
        f"  citation coverage    {_pct(stats['citation_coverage'])}",
        f"  grounded             {_pct(stats['grounded'])}",
        f"  answered             {_pct(stats['answered'])}",
        f"  failure rate         {_pct(stats['failed'])}",
        f"  invalid citations    {_fmt(stats['invalid_citations'], '', 0)}",
    ]
    return "\n".join(lines)


def _parse_window(args: argparse.Namespace) -> Window:
    now = datetime.now(UTC)
    if args.day:
        start = datetime.strptime(args.day, "%Y-%m-%d").replace(tzinfo=UTC)
        return Window(start, start + timedelta(days=1))
    days = int(args.since.rstrip("d"))
    return Window(now - timedelta(days=days), now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--since", default="7d", help="lookback window, e.g. 7d (default)")
    group.add_argument("--day", help="a single UTC day, YYYY-MM-DD")
    parser.add_argument(
        "--daily", action="store_true", help="break the window into one row per day"
    )
    parser.add_argument(
        "--follow", "-f", action="store_true", help="stream queries as they land"
    )
    parser.add_argument("--interval", type=float, default=3.0, help="--follow poll seconds")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        print("Langfuse keys not configured - nothing to report.", file=sys.stderr)
        return 1

    if args.follow:
        try:
            return follow(settings, args.interval)
        except KeyboardInterrupt:
            return 0

    window = _parse_window(args)

    if args.daily:
        print(f"{'day':<12}{'reqs':>6}{'p50 ms':>9}{'p95 ms':>9}{'$/req':>9}{'cover':>8}{'fail':>7}")
        day = window.start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < window.end:
            daily = Window(day, day + timedelta(days=1))
            stats = collect(settings, daily)
            print(
                f"{day:%Y-%m-%d}  {_fmt(stats['requests'], '', 0):>6}"
                f"{_fmt(stats['latency_p50_ms'], '', 0):>9}"
                f"{_fmt(stats['latency_p95_ms'], '', 0):>9}"
                f"{_fmt(stats['cost_per_request_usd'], '', 4):>9}"
                f"{_pct(stats['citation_coverage']):>8}{_pct(stats['failed']):>7}"
            )
            day += timedelta(days=1)
        return 0

    print(render(window, collect(settings, window)))

    slowest = worst_traces(settings, window)
    if slowest:
        print("\nSlowest requests:")
        for observation in slowest:
            latency = observation.get("latency")
            print(
                f"  {_fmt(latency, ' s', 1):>9}  {observation.get('startTime', '')[:19]}"
                f"  trace={observation.get('traceId')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
