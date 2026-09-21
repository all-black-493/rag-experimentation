"""Relationship questions with ground truth taken from the citation graph itself.

    uv run python eval/build_relationship_questions.py

For the most-cited authorities and statute provisions, asks "which judgments
cite / apply X" and records every judgment that does, from the edges. No model
is involved, so the truth is exact - and the questions are the ones the graph
expansion exists for.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings
from app.graph.store import CLASS_NAME
from app.vectorstore.client import weaviate_client

OUTPUT = Path(__file__).resolve().parent / "golden_relationships.jsonl"
MIN_CITERS = 4
PER_KIND = 5


def main() -> int:
    with weaviate_client(get_settings()) as client:
        urls: dict[str, str] = {}
        for name in ("CaseLaw", "Legislation"):
            for obj in client.collections.use(name).iterator(return_properties=["doc_id", "url"]):
                urls[obj.properties["doc_id"]] = obj.properties["url"]
        by_key: dict[tuple, dict] = {}
        for obj in client.collections.use(CLASS_NAME).iterator():
            e = obj.properties
            if e["source_collection"] != "case_law":
                continue
            if e["kind"] == "cites":
                label = e.get("parties") or e["target_ref"]
                key = ("cites", e.get("parties_key") or e["target_key"])
            else:
                if not e.get("provision"):
                    continue
                label = f"{e['target_ref']}"
                key = ("applies", f"{e['target_key']} § {e['provision']}")
            entry = by_key.setdefault(key, {"label": label, "sources": set()})
            entry["sources"].add(urls[e["source_doc_id"]])

    rows = []
    for kind in ("cites", "applies"):
        ranked = sorted(
            ((k, v) for k, v in by_key.items() if k[0] == kind and len(v["sources"]) >= MIN_CITERS),
            key=lambda kv: -len(kv[1]["sources"]),
        )[:PER_KIND]
        for i, (key, entry) in enumerate(ranked, start=1):
            question = (
                f"Which judgments cite {entry['label']}?"
                if kind == "cites"
                else f"Which judgments have applied {entry['label']}?"
            )
            rows.append(
                {
                    "id": f"relationship-{kind}-{i:02d}",
                    "question": question,
                    "ground_truth": f"{len(entry['sources'])} judgments in the corpus cite it.",
                    "sources": sorted(entry["sources"]),
                    "kind": "relationship",
                }
            )
    OUTPUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    for r in rows:
        print(f"{r['id']:<26} {len(r['sources']):>3} sources  {r['question']}", file=sys.stderr)
    print(f"{len(rows)} questions -> {OUTPUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
