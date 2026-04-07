"""
Embedding-based clustering utility.
Uses OpenAI embeddings + sklearn k-means to cluster items by semantic similarity.
"""
import logging
from typing import Callable

import numpy as np
from sklearn.cluster import KMeans

from utils.openai_client import get_embeddings

logger = logging.getLogger(__name__)


def embed_and_cluster(
    texts: list[str],
    n_clusters: int,
    *,
    max_cluster_size: int = 0,
    return_embeddings: bool = False,
) -> list[list[int]] | tuple[list[list[int]], np.ndarray]:
    """
    Embed texts and cluster into n_clusters groups via k-means.

    Returns list of clusters, where each cluster is a list of indices into `texts`.
    If max_cluster_size > 0, oversized clusters are split via sub-clustering.
    If return_embeddings=True, also returns the embedding matrix used for clustering.
    """
    if not texts:
        empty: list[list[int]] = []
        if return_embeddings:
            return empty, np.empty((0, 0), dtype=np.float32)
        return empty

    if len(texts) <= n_clusters:
        clusters = [[i] for i in range(len(texts))]
        if return_embeddings:
            logger.info(f"  Embedding {len(texts)} items...")
            embeddings = get_embeddings(texts)
            return clusters, embeddings
        return clusters

    logger.info(f"  Embedding {len(texts)} items...")
    embeddings = get_embeddings(texts)

    logger.info(f"  K-means clustering into {n_clusters} groups...")
    km = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
    labels = km.fit_predict(embeddings)

    # Group indices by cluster label
    clusters: list[list[int]] = [[] for _ in range(n_clusters)]
    for idx, label in enumerate(labels):
        clusters[label].append(idx)

    # Remove empty clusters
    clusters = [c for c in clusters if c]

    # Split oversized clusters if requested
    if max_cluster_size > 0:
        final = []
        for c in clusters:
            if len(c) > max_cluster_size:
                n_sub = max(2, (len(c) + max_cluster_size - 1) // max_cluster_size)
                sub_emb = embeddings[c]
                sub_km = KMeans(n_clusters=n_sub, n_init=5, random_state=42)
                sub_labels = sub_km.fit_predict(sub_emb)
                sub_clusters: list[list[int]] = [[] for _ in range(n_sub)]
                for i, sl in enumerate(sub_labels):
                    sub_clusters[sl].append(c[i])
                final.extend([sc for sc in sub_clusters if sc])
            else:
                final.append(c)
        clusters = final

    logger.info(f"  Clustering done: {len(clusters)} clusters, sizes {min(len(c) for c in clusters)}-{max(len(c) for c in clusters)}")

    if return_embeddings:
        return clusters, embeddings
    return clusters


def build_cluster_dicts(
    clusters: list[list[int]],
    items: list[dict],
    *,
    id_field: str,
    text_fn: Callable[[dict], str],
    cluster_id_prefix: str = "CL",
    embeddings: np.ndarray | None = None,
    max_representatives: int = 10,
) -> list[dict]:
    """
    Convert cluster index lists into dicts with item IDs and representative texts.

    Returns list of dicts like:
    {
        "cluster_id": "CL-01",
        "{id_field}s": ["id1", "id2", ...],
        "representative_texts": ["text1", "text2", ...],  # up to max_representatives per cluster
    }
    """
    result = []
    for ci, indices in enumerate(clusters):
        item_ids = [str(items[idx].get(id_field, idx)) for idx in indices]
        # Pick representative items.
        # If embeddings are available, choose texts nearest to cluster centroid.
        # This gives the labeling LLM tighter, more central examples.
        if len(indices) <= max_representatives:
            rep_indices = indices
        elif embeddings is not None and len(indices) > 0:
            sub_emb = embeddings[indices]
            centroid = np.mean(sub_emb, axis=0)
            centroid_norm = np.linalg.norm(centroid) + 1e-9
            sub_norm = np.linalg.norm(sub_emb, axis=1) + 1e-9
            sims = (sub_emb @ centroid) / (sub_norm * centroid_norm)
            top_local = np.argsort(-sims)[:max_representatives]
            rep_indices = [indices[int(i)] for i in top_local]
        else:
            step = len(indices) / max_representatives
            rep_indices = [indices[int(i * step)] for i in range(max_representatives)]
        rep_texts = [text_fn(items[idx]) for idx in rep_indices]

        result.append({
            "cluster_id": f"{cluster_id_prefix}-{ci + 1:02d}",
            f"{id_field}s": item_ids,
            "representative_texts": rep_texts,
        })
    return result
