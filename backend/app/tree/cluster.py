"""Group passages by meaning, for summarising - RAPTOR's clustering, simplified.

RAPTOR reduces the embeddings with UMAP and fits Gaussian mixtures, choosing
the number of clusters by BIC. The embeddings here are already small (384
dimensions), so the mixture is fitted on them directly, with diagonal
covariances so a cluster of ten points is well-conditioned, and the number
of components chosen by BIC around the target cluster size. Deterministic:
the same passages cluster the same way on every run.
"""

import numpy as np
from sklearn.mixture import GaussianMixture

_SEED = 0


def cluster(
    vectors: np.ndarray, *, target_size: int = 10, max_clusters: int = 64
) -> list[list[int]]:
    """Indices of the vectors, grouped. Small inputs are one group."""
    n = len(vectors)
    if n <= target_size:
        return [list(range(n))] if n else []
    centre = max(2, round(n / target_size))
    candidates = sorted(
        {k for k in (centre - 1, centre, centre + 1) if 2 <= k <= min(max_clusters, n - 1)}
    )
    best_k, best_bic = candidates[0], float("inf")
    for k in candidates:
        mixture = GaussianMixture(n_components=k, covariance_type="diag", random_state=_SEED)
        mixture.fit(vectors)
        bic = mixture.bic(vectors)
        if bic < best_bic:
            best_k, best_bic = k, bic
    labels = (
        GaussianMixture(n_components=best_k, covariance_type="diag", random_state=_SEED)
        .fit(vectors)
        .predict(vectors)
    )
    groups: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        groups.setdefault(int(label), []).append(index)
    # In label order, then by first member: stable across runs.
    return [groups[label] for label in sorted(groups)]
