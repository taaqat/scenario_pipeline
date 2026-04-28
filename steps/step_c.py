"""
Step C: Unexpected Scenario Generation
=======================================
Selected weak signals → cluster → expand into scenarios
"""
import json
import logging
import threading
import hashlib
from pathlib import Path

import pandas as pd

import config as cfg
from utils.llm_client import get_client
from utils.openai_client import get_openai_client
from utils.data_io import (
    read_json, save_json, save_excel, is_valid_batch,
    chunk_list, load_prompt, unwrap_rankings, apply_scores,
    save_checkpoint_if_due, rank_and_select, pick_final,
    compute_pool_size,
)
from utils.bilingual import save_split, translate_to_zh, strip_zh

logger = logging.getLogger(__name__)


def _c_pool_n() -> int:
    return compute_pool_size(cfg.C_GENERATE_N, cfg.C_OVERGEN_FACTOR, cfg.C_GENERATE_CAP)


def _c_phase2_signature(clusters: list[dict]) -> str:
    """Build a stable signature for C-Phase2 inputs + runtime context."""
    compact_clusters = [
        {
            "cluster_id": str(c.get("cluster_id", "")),
            "signal_ids": [str(sid) for sid in c.get("signal_ids", [])],
        }
        for c in clusters
    ]
    cp = getattr(cfg, "CLIENT_PROFILE", {}) or {}
    context = {
        "topic": str(getattr(cfg, "TOPIC", "") or ""),
        "timeframe": str(getattr(cfg, "TIMEFRAME", "") or ""),
        "industries": [str(x) for x in (cp.get("industries") or [])],
        "mode": str(getattr(cfg, "C_MODE", "") or ""),
        # C Phase2 generation prompt consumes writing style + topic.
        "writing_style": str(getattr(cfg, "WRITING_STYLE", "") or ""),
    }
    payload = json.dumps(
        {"clusters": compact_clusters, "context": context},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _save_c_phase2_checkpoint(
    checkpoint_path: Path,
    completed: dict[int, dict],
    total_clusters: int,
    clusters_signature: str,
):
    save_json(
        {
            "meta": {
                "total_clusters": total_clusters,
                "clusters_signature": clusters_signature,
            },
            "results": {str(k): v for k, v in completed.items()},
        },
        checkpoint_path,
    )


def _normalize_source_signals(
    raw_signals,
    valid_ja: dict[str, str],
    valid_zh: dict[str, str],
    fallback_ids: list[str],
) -> list[dict]:
    """Keep only valid source signal IDs; backfill from cluster IDs when needed."""
    normalized: list[dict] = []
    seen: set[str] = set()

    if isinstance(raw_signals, dict):
        raw_signals = [raw_signals]
    if not isinstance(raw_signals, list):
        raw_signals = []

    for sig in raw_signals:
        if not isinstance(sig, dict):
            continue
        sid = str(sig.get("signal_id", "")).strip()
        if not sid or sid in seen or sid not in valid_ja:
            continue
        item = {"signal_id": sid}
        if valid_ja.get(sid):
            item["title_ja"] = valid_ja[sid]
        if valid_zh.get(sid):
            item["title_zh"] = valid_zh[sid]
        normalized.append(item)
        seen.add(sid)

    # Ensure at least one grounded source signal exists.
    if not normalized:
        for sid in fallback_ids:
            sid = str(sid).strip()
            if not sid or sid in seen or sid not in valid_ja:
                continue
            item = {"signal_id": sid}
            if valid_ja.get(sid):
                item["title_ja"] = valid_ja[sid]
            if valid_zh.get(sid):
                item["title_zh"] = valid_zh[sid]
            normalized.append(item)
            seen.add(sid)
            if len(normalized) >= 3:
                break

    return normalized




# ── Phase 1 (cluster mode): K-means clustering ────
def phase1_cluster(selected_signals: list[dict] = None) -> list[dict]:
    """
    Cluster selected weak signals into thematic groups.
    Uses embedding + BERTopic (UMAP + HDBSCAN) for grouping; LLM only names each cluster.
    """
    if selected_signals is None:
        selected_signals = read_json(cfg.INTERMEDIATE_DIR / "b_phase3_dedup_selected.json")

    from utils.clustering import bertopic_cluster, build_cluster_dicts

    signal_texts = [
        (s.get("title_ja") or s.get("title") or "") + " " + (s.get("reasoning_ja") or s.get("reasoning") or "")
        for s in selected_signals
    ]

    pool_n = _c_pool_n()
    logger.info(f"Phase 1 (cluster): pool_n={pool_n} (deliver={cfg.C_GENERATE_N}, factor={cfg.C_OVERGEN_FACTOR}, cap={cfg.C_GENERATE_CAP}) via BERTopic (UMAP+HDBSCAN)")
    clusters, embeddings = bertopic_cluster(
        signal_texts,
        min_cluster_size=cfg.C_BERTOPIC_MIN_CLUSTER_SIZE,
        target_n_topics=pool_n,
        drop_outliers=cfg.C_BERTOPIC_DROP_OUTLIERS,
        return_embeddings=True,
    )

    # Build cluster dicts with signal IDs
    cluster_dicts = build_cluster_dicts(
        clusters, selected_signals,
        id_field="signal_id",
        text_fn=lambda s: s.get("title_ja") or s.get("title") or "",
        cluster_id_prefix="CL",
        embeddings=embeddings,
    )

    # LLM labels each cluster with a theme name
    llm = get_client()
    llm.set_step("C-cluster")

    label_tpl = load_prompt("c_phase1_label_clusters.txt")

    def make_label_prompt(item):
        cd = item
        rep_text = json.dumps(cd["representative_texts"], ensure_ascii=False, indent=1)
        return (label_tpl
                .replace("{num_signals}", str(len(cd["signal_ids"])))
                .replace("{representative_texts}", rep_text))

    label_results = llm.concurrent_batch_call(
        items=cluster_dicts,
        prompt_fn=make_label_prompt,
        model=cfg.MODEL_HEAVY,  # Quality matters: themes feed directly into scenario generation
        desc="C-Phase1 Label Clusters",
        max_workers=cfg.MAX_CONCURRENT,
    )

    # Merge LLM labels back into cluster dicts
    all_clusters = []
    for cd, label in zip(cluster_dicts, label_results):
        cluster = {
            "cluster_id": cd["cluster_id"],
            "theme_ja": "",
            "synthesis_hint_ja": "",
            "signal_ids": cd["signal_ids"],
            "centroid": cd.get("centroid"),
        }
        if isinstance(label, dict):
            cluster["theme_ja"] = label.get("theme_ja", "")
            cluster["synthesis_hint_ja"] = label.get("synthesis_hint_ja", "")
        elif isinstance(label, list) and label and isinstance(label[0], dict):
            cluster["theme_ja"] = label[0].get("theme_ja", "")
            cluster["synthesis_hint_ja"] = label[0].get("synthesis_hint_ja", "")
        all_clusters.append(cluster)

    # Log coverage
    all_input_ids = {str(s.get("signal_id", "")) for s in selected_signals} - {""}
    clustered_ids = set()
    for c in all_clusters:
        clustered_ids.update(str(sid) for sid in c.get("signal_ids", []))
    uncovered = all_input_ids - clustered_ids
    if uncovered:
        logger.warning(f"⚠ C-Phase1: {len(uncovered)}/{len(all_input_ids)} signals not in any cluster")
    else:
        logger.info(f"  Signal coverage: all {len(all_input_ids)} signals assigned to clusters")

    save_json(all_clusters, cfg.INTERMEDIATE_DIR / "c_phase1_clusters.json")
    logger.info(f"Phase 1 done: {len(all_clusters)} clusters")
    return all_clusters


# ── Phase 1 (cluster_pair mode): Cluster then randomly pair ────────
def phase1_cluster_pair(selected_signals: list[dict] = None) -> list[dict]:
    """
    Cluster-pair mode: run BERTopic first, then pair 2 clusters per
    pseudo-cluster. Each pseudo-cluster merges signals from 2 thematically
    distinct base clusters, creating inter-theme collision.

    Pair selection: sample 3 random candidate pairs, keep the one whose
    cluster centroids are farthest apart (cosine distance). Stays random
    but biases toward pairs that would never co-occur under similarity —
    responds to JRI's "human leap" critique without fully brute-forcing.
    Falls back to pure random if centroids are missing.
    Same API cost as cluster mode (pairing is local).
    """
    import random
    import numpy as np

    def _cos_dist(ca, cb):
        if not ca or not cb:
            return 0.0
        a = np.asarray(ca, dtype=float)
        b = np.asarray(cb, dtype=float)
        na = float(np.linalg.norm(a))
        nb = float(np.linalg.norm(b))
        if na == 0 or nb == 0:
            return 0.0
        return 1.0 - float(np.dot(a, b) / (na * nb))

    base_clusters = phase1_cluster(selected_signals)
    n_pairs = _c_pool_n()
    logger.info(f"Phase 1 (CLUSTER_PAIR): pairing {n_pairs} times from {len(base_clusters)} base clusters (deliver={cfg.C_GENERATE_N})")

    pairs = []
    for i in range(n_pairs):
        if len(base_clusters) < 2:
            a = b = base_clusters[0] if base_clusters else {}
        else:
            best = None
            best_d = -1.0
            for _ in range(3):
                ca, cb = random.sample(base_clusters, 2)
                d = _cos_dist(ca.get("centroid"), cb.get("centroid"))
                if d > best_d:
                    best_d = d
                    best = (ca, cb)
            a, b = best
        pairs.append({
            "cluster_id": f"PAIR-{i+1:03d}",
            "theme_ja": f"{a.get('theme_ja', '?')} × {b.get('theme_ja', '?')}",
            "synthesis_hint_ja": (
                f"異なる2つのテーマ（{a.get('theme_ja', '?')} と {b.get('theme_ja', '?')}）を"
                f"衝突させ、どちらか一方では生まれない予想外の未来を構築する"
            ),
            "signal_ids": list(a.get("signal_ids", [])) + list(b.get("signal_ids", [])),
        })

    save_json(pairs, cfg.INTERMEDIATE_DIR / "c_phase1_clusters.json")
    logger.info(f"Phase 1 (CLUSTER_PAIR) done: {n_pairs} paired pseudo-clusters")
    return pairs


# ── Phase 1 (signal_pair mode): Random 2-signal pairs ──────────────
def phase1_signal_pair(selected_signals: list[dict] = None) -> list[dict]:
    """
    Signal-pair mode: skip clustering entirely. Pick 2 random signals per
    pseudo-cluster. Maximum diversity — forces unexpected signal collisions.
    """
    import random

    if selected_signals is None:
        selected_signals = read_json(cfg.INTERMEDIATE_DIR / "b_phase3_dedup_selected.json")

    n_pairs = _c_pool_n()
    logger.info(f"Phase 1 (SIGNAL_PAIR): creating {n_pairs} random 2-signal pairs from {len(selected_signals)} signals (deliver={cfg.C_GENERATE_N})")

    pairs = []
    for i in range(n_pairs):
        if len(selected_signals) < 2:
            samples = selected_signals[:]
        else:
            samples = random.sample(selected_signals, 2)
        pairs.append({
            "cluster_id": f"SIG-{i+1:03d}",
            "theme_ja": "訊号の衝突",
            "synthesis_hint_ja": "無関係な2つの訊号を衝突させ、誰も想像しない未来を構築する",
            "signal_ids": [str(s.get("signal_id", "")) for s in samples],
        })

    save_json(pairs, cfg.INTERMEDIATE_DIR / "c_phase1_clusters.json")
    logger.info(f"Phase 1 (SIGNAL_PAIR) done: {n_pairs} 2-signal pairs")
    return pairs


# ── Phase 2: Generate scenarios ─────────────────────
def phase2_generate(
    clusters: list[dict] = None,
    selected_signals: list[dict] = None,
) -> list[dict]:
    """Generate Unexpected Scenarios from each cluster."""
    if clusters is None:
        clusters = read_json(cfg.INTERMEDIATE_DIR / "c_phase1_clusters.json")
    if selected_signals is None:
        selected_signals = read_json(cfg.INTERMEDIATE_DIR / "b_phase3_dedup_selected.json")

    # Build signal lookup
    signal_map = {str(s.get("signal_id") or i): s for i, s in enumerate(selected_signals)}

    llm = get_client()
    llm.set_step("C-generate")
    prompt_tpl = load_prompt("c_phase2_generate.txt")

    total_clusters = len(clusters)
    clusters_signature = _c_phase2_signature(clusters)
    indexed_clusters = [(i + 1, c) for i, c in enumerate(clusters)]

    # ── Checkpoint ──────────────────────────────────
    checkpoint_path = cfg.INTERMEDIATE_DIR / "c_phase2_checkpoint.json"
    completed: dict[int, dict] = {}
    if checkpoint_path.exists():
        try:
            ckpt = read_json(checkpoint_path)
            meta = ckpt.get("meta", {}) if isinstance(ckpt, dict) else {}
            saved_sig = meta.get("clusters_signature")
            saved_total = meta.get("total_clusters")
            if saved_sig != clusters_signature or saved_total != total_clusters:
                logger.info(
                    "  C-Phase2 checkpoint is stale (clusters changed) - starting fresh"
                )
            else:
                completed = {int(k): v for k, v in ckpt.get("results", {}).items()}
                logger.info(f"  C-Phase2 checkpoint: {len(completed)}/{total_clusters} done")
        except Exception:
            logger.warning("  C-Phase2 checkpoint load failed — starting fresh")

    remaining = [(i, idx, c) for i, (idx, c) in enumerate(indexed_clusters)
                 if i not in completed]
    logger.info(f"C-Phase2 Generate: {total_clusters} clusters, {len(remaining)} remaining")

    ckpt_lock = threading.Lock()

    def make_prompt(item):
        _, idx, cluster = item
        details = [strip_zh(signal_map.get(sid, {"signal_id": sid}))
                   for sid in cluster.get("signal_ids", [])]
        return (prompt_tpl
                .replace("{writing_style}", cfg.WRITING_STYLE)
                .replace("{topic}", cfg.TOPIC)
                .replace("{index}", str(idx))
                .replace("{cluster}", json.dumps(cluster, ensure_ascii=False, indent=1))
                .replace("{signal_details}", json.dumps(details, ensure_ascii=False, indent=1)))

    def on_done(flat_idx, result):
        abs_idx = remaining[flat_idx][0]
        with ckpt_lock:
            if result:
                completed[abs_idx] = result
            if len(completed) % 10 == 0 or len(completed) == total_clusters:
                _save_c_phase2_checkpoint(
                    checkpoint_path,
                    completed,
                    total_clusters,
                    clusters_signature,
                )

    if remaining:
        llm.concurrent_batch_call(
            items=remaining,
            prompt_fn=make_prompt,
            model=cfg.MODEL_HEAVY,
            desc="C-Phase2 Generate",
            max_workers=cfg.MAX_CONCURRENT,
            on_item_done=on_done,
            temperature=0.6,
            use_tool=True,
        )
        _save_c_phase2_checkpoint(
            checkpoint_path,
            completed,
            total_clusters,
            clusters_signature,
        )
    else:
        logger.info("  All C-Phase2 clusters complete — assembling from checkpoint")

    cluster_signal_ids = {
        i: [str(sid) for sid in (clusters[i].get("signal_ids", []) if i < len(clusters) else [])]
        for i in range(total_clusters)
    }
    all_scenarios = []
    failed_clusters = []
    for i in range(total_clusters):
        r = completed.get(i)
        if r:
            if isinstance(r, list):
                for item in r:
                    if isinstance(item, dict):
                        item = dict(item)
                        item["_cluster_idx"] = i
                        all_scenarios.append(item)
            elif isinstance(r, dict):
                item = dict(r)
                item["_cluster_idx"] = i
                all_scenarios.append(item)
        else:
            failed_clusters.append(i)
    if failed_clusters:
        logger.warning(
            f"⚠ C-Phase2: {len(failed_clusters)}/{total_clusters} clusters failed to generate scenarios: "
            f"{failed_clusters[:10]}{'...' if len(failed_clusters) > 10 else ''}"
        )

    # Filter out non-dict entries (malformed LLM responses)
    pre_filter = len(all_scenarios)
    all_scenarios = [s for s in all_scenarios if isinstance(s, dict)]
    if len(all_scenarios) < pre_filter:
        logger.warning(f"⚠ C-Phase2: filtered out {pre_filter - len(all_scenarios)} malformed entries")

    # Normalize source_signals to current B selection and fix bilingual titles.
    title_ja_map = {str(s.get("signal_id")): s.get("title_ja", "") for s in selected_signals}
    # Load B zh output for Chinese titles (already translated in Step B)
    b_zh_path = cfg.OUTPUT_DIR / "B_selected_weak_signals_zh.json"
    title_zh_map = {}
    if b_zh_path.exists():
        b_zh = read_json(b_zh_path)
        title_zh_map = {str(s.get("signal_id")): s.get("title", "") for s in b_zh}

    for scenario in all_scenarios:
        ci = scenario.get("_cluster_idx")
        fallback_ids = cluster_signal_ids.get(ci, []) if isinstance(ci, int) else []
        scenario["source_signals"] = _normalize_source_signals(
            scenario.get("source_signals"),
            title_ja_map,
            title_zh_map,
            fallback_ids,
        )
        scenario.pop("_cluster_idx", None)

    # Enforce stable sequential IDs for downstream ranking/traceability
    for idx, s in enumerate(all_scenarios, 1):
        s["scenario_id"] = f"C-{idx}"

    save_json(all_scenarios, cfg.INTERMEDIATE_DIR / "c_phase2_scenarios.json")

    logger.info(f"Phase 2 done: {len(all_scenarios)} scenarios generated")
    return all_scenarios


# ── Phase 3: Rank & Select ───────────────────────────
def phase3_rank(scenarios: list[dict] = None) -> list[dict]:
    """Rank scenarios, keep all gate-passing items, then add global review flags."""
    if scenarios is None:
        scenarios = read_json(cfg.INTERMEDIATE_DIR / "c_phase2_scenarios.json")

    llm = get_openai_client()
    llm.set_step("C-rank")

    C_DIMS = ["unexpectedness", "social_impact", "uncertainty"]

    c_summary_fn = lambda s: {
        "scenario_id": s.get("scenario_id"),
        "title_ja": s.get("title_ja", ""),
        "overview_ja": (s.get("overview_ja") or "")[:500],
        "source_signals": [
            sig.get("title_ja", "") for sig in s.get("source_signals", [])
        ],
    }

    scenarios, final = rank_and_select(
        scenarios, C_DIMS,
        load_prompt("c_phase3_rank.txt"),
        llm, cfg.RANK_MODEL,
        summary_fn=c_summary_fn,
        prompt_vars={"topic": cfg.TOPIC},
        step_label="C-Phase3",
        weights=cfg.C_WEIGHTS,
    )

    # Final pick: one LLM call selects K from the pool, balancing score +
    # mechanism diversity + title uniqueness, and rewrites titles
    # that are too jargony/abstract.
    # NOTE: C is the "Unexpected" step. By design it MUST NOT be constrained
    # to the project topic — per JRI feedback, C should move AWAY from the
    # topic to expose weak-signal-driven surprises. topic="" disables the
    # topic-relevance criterion in pick_final.
    final = pick_final(
        final, k=cfg.C_GENERATE_N, llm=llm, model=cfg.RANK_MODEL,
        fields=["title_ja", "overview_ja", "who_ja", "what_how_ja"],
        topic="", step_label="C-Phase3",
    )

    final.sort(key=lambda s: (
        -(s.get("weighted_score", 0) or 0),
        -(s.get("total_score", 0) or 0),
        str(s.get("scenario_id", "")),
    ))

    # Translate and save
    if getattr(cfg, "TRANSLATE_ENABLED", False):
        oai = get_openai_client()
        oai.set_step("C-translate")
        final = translate_to_zh(final, oai, cfg.TRANSLATE_MODEL)
    save_split(final, cfg.OUTPUT_DIR, "C_unexpected_scenarios")

    df = pd.DataFrame([
        {
            "scenario_id": s.get("scenario_id"),
            "total_score": s.get("total_score"),
            "title_ja": s.get("title_ja", ""),
            "title_zh": s.get("title_zh", ""),
            "overview_ja": s.get("overview_ja", ""),
            "overview_zh": s.get("overview_zh", ""),
            "why_ja": "\n".join(s.get("why_ja", [])),
            "why_zh": "\n".join(s.get("why_zh", [])),
            "who_ja": "\n".join(s.get("who_ja", [])),
            "who_zh": "\n".join(s.get("who_zh", [])),
            "where_ja": s.get("where_ja", ""),
            "where_zh": s.get("where_zh", ""),
            "what_how_ja": "\n".join(s.get("what_how_ja", [])),
            "what_how_zh": "\n".join(s.get("what_how_zh", [])),
            "timeline_decade": s.get("timeline_decade", ""),
            "timeline_description_ja": s.get("timeline_description_ja", ""),
            "timeline_description_zh": s.get("timeline_description_zh", ""),
            "source_signals_ja": "\n".join(
                f"{sig.get('signal_id', '')}: {sig.get('title_ja', '')}"
                for sig in s.get("source_signals", [])
            ),
            "source_signals_zh": "\n".join(
                f"{sig.get('signal_id', '')}: {sig.get('title_zh', '')}"
                for sig in s.get("source_signals", [])
            ),
            "ranking_note_ja": s.get("ranking_note_ja", ""),
            "ranking_note_zh": s.get("ranking_note_zh", ""),
        }
        for s in final
    ])
    save_excel(df, cfg.OUTPUT_DIR / "C_unexpected_scenarios.xlsx")

    logger.info(f"Phase 3 done: {len(final)} scenarios written to output after gate filter and review")
    return final


# ── Run All ─────────────────────────────────────────
def run() -> list[dict]:
    logger.info("=" * 60)
    logger.info(f"Step C: Unexpected Scenario Generation (mode={cfg.C_MODE})")
    logger.info("=" * 60)

    if cfg.C_MODE == "cluster_pair":
        clusters = phase1_cluster_pair()
    elif cfg.C_MODE == "signal_pair":
        clusters = phase1_signal_pair()
    else:
        if cfg.C_MODE not in ("cluster", None, ""):
            logger.warning(f"Unknown C_MODE={cfg.C_MODE!r} - falling back to cluster mode")
        clusters = phase1_cluster()
    scenarios = phase2_generate(clusters)
    final = phase3_rank(scenarios)

    logger.info(f"Step C complete: {len(final)} scenarios written to output")
    return final


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
