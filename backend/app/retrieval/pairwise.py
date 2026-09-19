"""duoT5 pairwise reranking - the optional third stage.

Stage 2 (the cross-encoder) scores each passage against the query independently:
it can say "both look relevant" but never "this one more than that one". duoT5 is
trained on exactly that comparison - given a query and two passages, it emits
`true` if the first is the more relevant. Comparing candidates against each other
catches orderings a pointwise scorer has no way to express.

It is deliberately off by default, because it is quadratic. Every ordered pair of
the top k costs a forward pass: k=5 is 20 comparisons, k=10 is 90, k=20 is 380.
That is fine over a handful of finalists and ruinous over a candidate pool, which
is why this runs *after* the cross-encoder has cut 60 down to a few, never instead
of it.

Aggregation is symmetric pairwise preference counting (the SYM-SUM scheme from the
duoT5 paper): each passage accumulates its win probability across both orderings
of every pair it appears in. Both orderings matter - the model is not guaranteed
to be consistent when the passages are swapped, and averaging the two directions
cancels the positional bias.
"""

import logging
from itertools import permutations

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_model_cache: dict[str, object] = {}


class PairwiseReranker:
    """Reorders a short list by pairwise preference."""

    def __init__(self, model_name: str, max_candidates: int):
        self._model_name = model_name
        self._max_candidates = max_candidates

    @property
    def _pipeline(self):
        if self._model_name not in _model_cache:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            logger.info("loading pairwise reranker %s", self._model_name)
            tokenizer = AutoTokenizer.from_pretrained(self._model_name)
            model = AutoModelForSeq2SeqLM.from_pretrained(self._model_name)
            model.eval()
            _model_cache[self._model_name] = (tokenizer, model)
        return _model_cache[self._model_name]

    def _preference(self, query: str, a: str, b: str) -> float:
        """P(a is more relevant than b), from the model's true/false logits."""
        import torch

        tokenizer, model = self._pipeline
        # The prompt shape duoT5 was trained on; deviating from it degrades the
        # scores silently, since the model still emits *something*.
        prompt = f"Query: {query} Document0: {a} Document1: {b} Relevant:"
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)

        with torch.no_grad():
            out = model.generate(
                **inputs, max_new_tokens=1, output_scores=True, return_dict_in_generate=True
            )

        logits = out.scores[0][0]
        true_id = tokenizer.encode("true", add_special_tokens=False)[0]
        false_id = tokenizer.encode("false", add_special_tokens=False)[0]
        pair = torch.softmax(torch.stack([logits[true_id], logits[false_id]]), dim=0)
        return float(pair[0])

    def rerank(self, documents: list[Document], query: str) -> list[Document]:
        """Reorder the head of the list; anything past the cutoff keeps its order."""
        head = documents[: self._max_candidates]
        tail = documents[self._max_candidates :]
        if len(head) < 2:
            return documents

        scores = dict.fromkeys(range(len(head)), 0.0)
        for i, j in permutations(range(len(head)), 2):
            scores[i] += self._preference(query, head[i].page_content, head[j].page_content)

        order = sorted(range(len(head)), key=lambda i: scores[i], reverse=True)
        reordered = [
            Document(
                head[i].page_content,
                metadata={**head[i].metadata, "pairwise_score": scores[i]},
            )
            for i in order
        ]
        return reordered + tail
