"""
Step C: Unexpected Scenario Generation
=======================================
Selected weak signals → cluster → expand into scenarios
"""
import json
import logging
import threading
from pathlib import Path

import pandas as pd

import config as cfg
from utils.llm_client import get_client
from utils.openai_client import get_openai_client
from utils.data_io import (
    read_json, save_json, save_excel, is_valid_batch,
    chunk_list, load_prompt, unwrap_rankings, apply_scores,
    save_checkpoint_if_due, rank_and_select, llm_review, enforce_gate,
)
from utils.bilingual import save_split, translate_to_zh, strip_zh

logger = logging.getLogger(__name__)


# ── Phase 1: Cluster signals ───────────────────────
def phase1_cluster(selected_signals: list[dict] = None) -> list[dict]:
    """
    Cluster selected weak signals into thematic groups.
    Uses embedding + k-means for grouping, LLM only for naming each cluster.
    """
    if selected_signals is None:
        selected_signals = read_json(cfg.INTERMEDIATE_DIR / "b_phase3_dedup_selected.json")

    from utils.clustering import embed_and_cluster, build_cluster_dicts

    # Build text for each signal (used for embedding)
    signal_texts = [
        (s.get("title_ja") or s.get("title") or "") + " " + (s.get("reasoning_ja") or s.get("reasoning") or "")
        for s in selected_signals
    ]

    # Embedding + k-means clustering
    logger.info(f"Phase 1: clustering {len(selected_signals)} signals into {cfg.C_GENERATE_N} clusters via embedding + k-means")
    clusters, embeddings = embed_and_cluster(
        signal_texts,
        cfg.C_GENERATE_N,
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
        }
        if isinstance(label, dict):
            cluster["theme_ja"] = label.get("theme_ja", "")
            cluster["synthesis_hint_ja"] = label.get("synthesis_hint_ja", "")
        elif isinstance(label, list) and label:
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
    signal_map = {s.get("signal_id", str(i)): s for i, s in enumerate(selected_signals)}

    llm = get_client()
    llm.set_step("C-generate")
    prompt_tpl = load_prompt("c_phase2_generate.txt")

    total_clusters = len(clusters)
    indexed_clusters = [(i + 1, c) for i, c in enumerate(clusters)]

    # ── Checkpoint ──────────────────────────────────
    checkpoint_path = cfg.INTERMEDIATE_DIR / "c_phase2_checkpoint.json"
    completed: dict[int, dict] = {}
    if checkpoint_path.exists():
        try:
            ckpt = read_json(checkpoint_path)
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
                save_json({"results": {str(k): v for k, v in completed.items()}},
                          checkpoint_path)

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
        save_json({"results": {str(k): v for k, v in completed.items()}}, checkpoint_path)
    else:
        logger.info("  All C-Phase2 clusters complete — assembling from checkpoint")

    all_scenarios = []
    failed_clusters = []
    for i in range(total_clusters):
        r = completed.get(i)
        if r:
            if isinstance(r, list):
                all_scenarios.extend(r)
            elif isinstance(r, dict):
                all_scenarios.append(r)
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

    # Fix source_signal titles: use bilingual title_ja / title_zh
    title_ja_map = {str(s.get("signal_id")): s.get("title_ja", "") for s in selected_signals}
    # Load B zh output for Chinese titles (already translated in Step B)
    b_zh_path = cfg.OUTPUT_DIR / "B_selected_weak_signals_zh.json"
    title_zh_map = {}
    if b_zh_path.exists():
        b_zh = read_json(b_zh_path)
        title_zh_map = {str(s.get("signal_id")): s.get("title", "") for s in b_zh}
    for scenario in all_scenarios:
        for sig in scenario.get("source_signals", []):
            sid = str(sig.get("signal_id", ""))
            # Set title_ja from B ja data
            ja = title_ja_map.get(sid, sig.get("title", ""))
            if ja:
                sig["title_ja"] = ja
            # Set title_zh from B zh data
            zh = title_zh_map.get(sid, "")
            if zh:
                sig["title_zh"] = zh
            sig.pop("title", None)  # remove bare key so save_split works correctly

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
        min_dim_scores=cfg.C_MIN_DIM_SCORES,
    )

    # LLM global review for duplicates, weak source & weak logic
    final = llm_review(
        final, llm, cfg.RANK_MODEL,
        step="C",
        summary_fn=c_summary_fn,
        prompt_vars={"topic": cfg.TOPIC},
        step_label="C-Phase3",
    )

    final = enforce_gate(final, cfg.C_MIN_DIM_SCORES, step_label="C-Phase3")

    # Translate and save
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
    logger.info("Step C: Unexpected Scenario Generation")
    logger.info("=" * 60)

    clusters = phase1_cluster()
    scenarios = phase2_generate(clusters)
    final = phase3_rank(scenarios)

    logger.info(f"Step C complete: {len(final)} scenarios written to output")
    return final


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
