"""Draft a golden dataset for the legal corpus.

    uv run python eval/build_golden.py ../corpus/all_chunks.json --anthropic-api-key ...

For a seeded sample of documents, takes one substantive passage and asks the
model to write a question that passage answers, with the answer. The passage
comes from the *reconstructed* document, not a raw window, so questions are
never about a sentence cut in half.

A draft, not a ground truth: the output is reviewed by hand before it is
committed - the point of a golden set is that a person vouched for it.

Runs in the eval environment (see eval/README.md); it needs only the app's
corpus module, which is stdlib plus nothing.
"""

import argparse
import json
import random
import sys
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR.parent))
from app.corpus.documents import SourceDocument, reconstruct

# Documents longer than this are skipped as sources: their windows would
# dominate the CI slice, and a 1,900-window Act is a poor place to draw a
# single passage from anyway.
MAX_WINDOWS = 200
# A passage is drawn from this far into the document, past the header block a
# judgment opens with and an Act's short title and arrangement of sections.
PASSAGE_OFFSET = 0.35
PASSAGE_CHARS = 1800


class Draft(BaseModel):
    question: str = Field(
        description="One specific question a Kenyan lawyer or paralegal might ask that this "
        "passage answers. Self-contained: name the Act, offence, party or subject so the "
        "question makes sense without seeing the passage."
    )
    ground_truth: str = Field(
        description="The answer in one or two sentences, using only what the passage says."
    )
    answerable: bool = Field(
        description="False if the passage is boilerplate, a table of contents, or otherwise "
        "has nothing a real question would target."
    )


PROMPT = """You are preparing evaluation questions for a legal research assistant over Kenyan law.

Source: {title} ({kind})

Passage:
\"\"\"
{passage}
\"\"\"

Write one question this passage answers, and the answer. The question must be
specific enough that a good search over Kenyan legislation and case law would
find this passage, and must not depend on seeing it."""


def passage_of(document: SourceDocument) -> str:
    start = int(len(document.text) * PASSAGE_OFFSET)
    return document.text[start : start + PASSAGE_CHARS]


def sample_documents(rows: list[dict], per_collection: int, seed: int) -> list[SourceDocument]:
    windows_per_url: dict[str, int] = {}
    for row in rows:
        windows_per_url[row["metadata"]["url"]] = row["metadata"]["total_chunks"]

    rng = random.Random(seed)
    chosen = []
    for collection in ("legislation", "case_law"):
        pool = [
            d
            for d in reconstruct(rows)
            if d.collection == collection and windows_per_url[d.url] <= MAX_WINDOWS
        ]
        chosen.extend(rng.sample(pool, per_collection))
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--anthropic-api-key", required=True)
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--per-collection", type=int, default=25)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path, default=EVAL_DIR / "golden_dataset.jsonl")
    args = parser.parse_args(argv)

    rows = json.loads(args.corpus.read_text())
    documents = sample_documents(rows, args.per_collection, args.seed)
    drafter = ChatAnthropic(
        model=args.model, anthropic_api_key=args.anthropic_api_key, max_tokens=1024
    ).with_structured_output(Draft)

    written = 0
    with args.output.open("w") as out:
        for i, document in enumerate(documents, start=1):
            draft: Draft = drafter.invoke(
                PROMPT.format(
                    title=document.title,
                    kind="Act" if document.collection == "legislation" else "judgment",
                    passage=passage_of(document),
                )
            )
            if not draft.answerable:
                print(f"skip {document.title[:60]}: not answerable", file=sys.stderr)
                continue
            written += 1
            out.write(
                json.dumps(
                    {
                        "id": f"{document.collection}-{written:02d}",
                        "question": draft.question,
                        "ground_truth": draft.ground_truth,
                        "source": document.url,
                        "collection": document.collection,
                        "title": document.title,
                    }
                )
                + "\n"
            )
            print(f"{i}/{len(documents)} {document.collection}: {draft.question}", file=sys.stderr)
    print(f"{written} questions written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
