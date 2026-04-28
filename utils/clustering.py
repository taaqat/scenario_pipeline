"""
Embedding-based clustering utility.
Uses OpenAI embeddings + UMAP + HDBSCAN (BERTopic) to cluster items by semantic similarity.
"""
import logging
from typing import Callable

import numpy as np

from utils.openai_client import get_embeddings

logger = logging.getLogger(__name__)


def bertopic_cluster(
    texts: list[str],
    *,
    min_cluster_size: int = 30,
    target_n_topics: int | None = None,
    drop_outliers: bool = True,
    return_embeddings: bool = False,
):
    """
    BERTopic-based clustering: OpenAI embeddings → UMAP dim reduction → HDBSCAN.
    Produces naturally-sized clusters (big mainstream + small specialty groups +
    an outlier bucket for noise). Diversity-friendly compared to k-means, which
    forces balanced cluster sizes and absorbs edge angles into mainstream groups.

    target_n_topics: if set, hierarchical-merge HDBSCAN's raw output down to this count.
    drop_outliers:   if True, the HDBSCAN -1 noise bucket is discarded (recommended
                     for downstream LLM labeling — the bucket is incoherent).
    """
    if not texts:
        empty: list[list[int]] = []
        if return_embeddings:
            return empty, np.empty((0, 0), dtype=np.float32)
        return empty

    logger.info(f"  Embedding {len(texts)} items...")
    embeddings = np.asarray(get_embeddings(texts))

    from bertopic import BERTopic
    from umap import UMAP
    from hdbscan import HDBSCAN

    logger.info(
        f"  BERTopic: min_cluster_size={min_cluster_size}, "
        f"target_n_topics={target_n_topics}, drop_outliers={drop_outliers}"
    )

    umap_model = UMAP(
        n_neighbors=15, n_components=5, min_dist=0.0,
        metric="cosine", random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )
    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        calculate_probabilities=False,
        verbose=False,
    )
    topics, _ = topic_model.fit_transform(texts, embeddings=embeddings)

    if target_n_topics is not None and target_n_topics > 0:
        topic_model.reduce_topics(texts, nr_topics=target_n_topics)
        topics = topic_model.topics_

    topic_to_indices: dict[int, list[int]] = {}
    for idx, t in enumerate(topics):
        topic_to_indices.setdefault(int(t), []).append(idx)

    sorted_ids = sorted(t for t in topic_to_indices if t != -1)
    clusters: list[list[int]] = [topic_to_indices[t] for t in sorted_ids]
    outlier_count = len(topic_to_indices.get(-1, []))
    if not drop_outliers and outlier_count:
        clusters.append(topic_to_indices[-1])

    if not clusters:
        logger.warning("  BERTopic produced 0 real clusters — falling back to whole-corpus single cluster")
        clusters = [list(range(len(texts)))]

    sizes = [len(c) for c in clusters]
    logger.info(
        f"  BERTopic clusters: {len(clusters)} groups, sizes {min(sizes)}-{max(sizes)} "
        f"(outliers {'dropped' if drop_outliers else 'kept'}: {outlier_count})"
    )

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

        # Centroid — kept on the dict so downstream (e.g. anti-similarity pairing)
        # can compute pairwise cluster distance without re-embedding.
        centroid = None
        if embeddings is not None and len(indices) > 0:
            centroid = np.mean(embeddings[indices], axis=0)

        # Pick representative items.
        # If embeddings are available, choose texts nearest to cluster centroid.
        # This gives the labeling LLM tighter, more central examples.
        if len(indices) <= max_representatives:
            rep_indices = indices
        elif centroid is not None:
            sub_emb = embeddings[indices]
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
            "centroid": centroid.tolist() if centroid is not None else None,
        })
    return result
