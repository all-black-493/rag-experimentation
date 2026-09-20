"""Thematic questions whose ground truth is a set of judgments, defined by wording.

    uv run python eval/build_topic_questions.py

"How have courts treated X" has no single right passage; it has a set of
judgments that treat X. The set is defined here without a model: every
judgment whose text contains the phrases that name the theme. Exact, if
narrow - a judgment that treats the theme in other words is missed, which
only makes the set a stricter test. These are the questions a topic tree
(RAPTOR) exists for; the benchmark scores them like the relationship set.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import get_settings
from app.vectorstore.client import weaviate_client
from weaviate.classes.query import Filter

OUTPUT = Path(__file__).resolve().parent / "golden_topics.jsonl"
MIN_DOCS = 5
MAX_DOCS = 80

# (question, phrases every judgment in the set must contain)
THEMES = [
    (
        "How have courts treated the prosecution's burden to show compelling reasons to deny bail?",
        ["compelling reasons", "bail"],
    ),
    (
        "How do courts assess the age of a complainant in a defilement case?",
        ["defilement", "age assessment"],
    ),
    ("When have courts awarded mesne profits against a tenant holding over?", ["mesne profits"]),
    ("How have courts dealt with distress for rent levied by a landlord?", ["distress for rent"]),
    (
        "What have courts said about termination of employment during probation?",
        ["probation", "termination"],
    ),
    ("How do courts treat a dying declaration as evidence?", ["dying declaration"]),
    (
        "When is a confession admissible after a trial within a trial?",
        ["trial within a trial", "confession"],
    ),
    ("How have courts applied the doctrine of adverse possession?", ["adverse possession"]),
    (
        "What do courts require before granting a temporary injunction?",
        ["temporary injunction", "prima facie"],
    ),
    (
        "How have courts treated identification by a single witness at night?",
        ["single identifying witness"],
    ),
    ("When do courts set aside a default judgment?", ["default judgment", "set aside"]),
    (
        "How have courts dealt with the sentence for robbery with violence?",
        ["robbery with violence", "sentence"],
    ),
]


def main() -> int:
    rows = []
    with weaviate_client(get_settings()) as client:
        case_law = client.collections.use("CaseLaw")
        for i, (question, phrases) in enumerate(THEMES, start=1):
            # By document: a judgment qualifies when each phrase appears in
            # some passage of it, not necessarily the same passage.
            urls: set[str] | None = None
            for phrase in phrases:
                response = case_law.query.fetch_objects(
                    filters=Filter.by_property("text").like(f"*{phrase}*"),
                    limit=10_000,
                    return_properties=["url"],
                )
                found = {obj.properties["url"] for obj in response.objects}
                urls = found if urls is None else urls & found
            urls = urls or set()
            if len(urls) < MIN_DOCS:
                print(f"skipping ({len(urls)} judgments): {question}", file=sys.stderr)
                continue
            rows.append(
                {
                    "id": f"topic-{i:02d}",
                    "question": question,
                    "ground_truth": f"Judgments whose text contains: {', '.join(phrases)}.",
                    "sources": sorted(urls)[:MAX_DOCS],
                    "phrases": phrases,
                    "kind": "topic",
                }
            )
            print(f"{len(urls):>4} judgments  {question}")
    OUTPUT.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"\n{len(rows)} questions -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
