"""
Step A-1: Expected Scenario Generation
=======================================
4-phase pipeline for processing 7000+ articles:
  Phase 1: Batch summarize articles (light model, save tokens)
  Phase 2: Cluster summaries into structural themes
  Phase 3: Generate Expected Scenarios from themes
    Phase 4: Rank, gate filter, and global review
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
    read_input, read_json, save_json, save_excel,
    chunk_list, chunk_dataframe, df_to_records, is_valid_batch,
    load_prompt, unwrap_rankings, apply_scores, save_checkpoint_if_due,
    rank_and_select, pick_final, compute_pool_size,
)
from utils.bilingual import save_split, translate_to_zh, strip_zh

logger = logging.getLogger(__name__)


def _a1_phase3_signature(themes: list[dict]) -> str:
    """Build a stable signature for Phase3 inputs + runtime context."""
    compact_themes = [
        {
            "theme_id": str(t.get("theme_id", "")),
            "related_article_ids": [str(aid) for aid in t.get("related_article_ids", [])],
        }
        for t in themes
    ]
    cp = getattr(cfg, "CLIENT_PROFILE", {}) or {}
    context = {
        "topic": str(getattr(cfg, "TOPIC", "") or ""),
        "timeframe": str(getattr(cfg, "TIMEFRAME", "") or ""),
        "industries": [str(x) for x in (cp.get("industries") or [])],
        "industries_ja": [str(x) for x in (cp.get("industries_ja") or [])],
        # A1 Phase3 prompt uses writing style directly, so include it in staleness checks.
        "writing_style": str(getattr(cfg, "WRITING_STYLE", "") or ""),
    }
    payload = json.dumps(
        {"themes": compact_themes, "context": context},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _save_a1_phase3_checkpoint(
    checkpoint_path: Path,
    completed: dict[int, dict],
    total_themes: int,
    themes_signature: str,
):
    save_json(
        {
            "meta": {
                "total_themes": total_themes,
                "themes_signature": themes_signature,
            },
            "results": {str(k): v for k, v in completed.items()},
        },
        checkpoint_path,
    )


def _build_row_num_map(input_file: Path) -> dict:
    """Build {str(article_id): {"row_num": int, "pub_year": int|None}} from original Excel."""
    import pandas as pd
    df = read_input(input_file)
    df["_pub_dt"] = pd.to_datetime(df.get("published_at"), errors="coerce")
    result = {}
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        id_str = str(row.get("id", ""))
        if id_str and id_str not in ("nan", ""):
            yr = int(row["_pub_dt"].year) if pd.notna(row.get("_pub_dt")) else None
            result[id_str] = {"row_num": i, "pub_year": yr}
    return result


def _format_summary(s: dict) -> dict:
    """Format a single enriched summary for injection into the generate prompt."""
    return {
        "row_num": s.get("row_num"),
        "title_ja": s.get("title_ja", ""),
        "source": s.get("source", ""),
        "key_data": (s.get("key_data") or [])[:4],
    }


def _find_relevant_summaries(
    theme: dict, summaries: list[dict], top_k: int = 12, min_year: int = 2020
) -> list[dict]:
    """
    Select the most relevant article summaries for a theme.

    Strategy:
    1. First, use related_article_ids from Phase 2 clustering (semantic match by LLM).
    2. If not enough, backfill with bigram similarity (lightweight fallback).
    This ensures Phase 2's article→theme associations are preserved into Phase 3.
    """
    # ── Step 1: Pull articles by related_article_ids from Phase 2 ──
    related_ids = {str(aid) for aid in theme.get("related_article_ids", []) if aid}
    summary_by_aid = {}
    for s in summaries:
        aid = str(s.get("article_id", ""))
        if aid and aid not in ("nan", ""):
            summary_by_aid[aid] = s

    direct_matches = []
    for aid in related_ids:
        s = summary_by_aid.get(aid)
        if s and s.get("row_num"):
            pub_year = s.get("pub_year")
            if pub_year and pub_year < min_year:
                continue
            direct_matches.append(s)

    # If we already have enough from direct matches, return them
    if len(direct_matches) >= top_k:
        return [_format_summary(s) for s in direct_matches[:top_k]]

    # ── Step 2: Backfill remaining slots with bigram similarity ──
    already_ids = {str(s.get("article_id", "")) for s in direct_matches}

    theme_text = (
        (theme.get("theme_name_ja") or "") + " " +
        (theme.get("structural_direction_ja") or "")
    )
    theme_bigrams = {theme_text[i:i + 2] for i in range(len(theme_text) - 1)}

    scored: list[tuple[int, dict]] = []
    for s in summaries:
        if not s.get("row_num"):
            continue
        aid = str(s.get("article_id", ""))
        if aid in already_ids:
            continue
        pub_year = s.get("pub_year")
        if pub_year and pub_year < min_year:
            continue
        candidate = (
            (s.get("title_ja") or "") + " " +
            " ".join(s.get("trend_keywords_ja") or [])
        )
        candidate_bigrams = {candidate[i:i + 2] for i in range(len(candidate) - 1)}
        score = len(theme_bigrams & candidate_bigrams)
        scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    remaining_slots = top_k - len(direct_matches)
    backfill = [s for _, s in scored[:remaining_slots]]

    return [_format_summary(s) for s in direct_matches + backfill]


# ── Phase 1: Batch Summarize ────────────────────────
def phase1_summarize(input_file: Path = None) -> list[dict]:
    """
    Read articles → concurrent batch summarize → save intermediate JSON.
    Supports checkpoint/resume: re-running skips already-completed batches.
    """
    input_file = input_file or cfg.A1_INPUT_FILE
    llm = get_client()
    llm.set_step("A1-summarize")
    prompt_tpl = load_prompt("a1_phase1_summarize.txt")

    nrows = cfg.SMOKE_ROWS if cfg.SMOKE_TEST else None
    logger.info(f"Phase 1: Loading articles from {input_file}" + (" [SMOKE TEST]" if nrows else ""))
    df = read_input(input_file, nrows=nrows)
    logger.info(f"  Total articles: {len(df)}")

    batches = chunk_dataframe(df, cfg.A1_PHASE1_BATCH)
    total_batches = len(batches)
    logger.info(f"  Batches: {total_batches} × {cfg.A1_PHASE1_BATCH}")

    # ── Checkpoint: load completed batch results ────
    checkpoint_path = cfg.INTERMEDIATE_DIR / "a1_phase1_checkpoint.json"
    completed: dict[int, list] = {}   # {abs_batch_idx: [summaries]}
    if checkpoint_path.exists():
        try:
            ckpt = read_json(checkpoint_path)
            completed = {int(k): v for k, v in ckpt.get("batch_results", {}).items()}
            non_empty = sum(1 for v in completed.values() if v)
            logger.info(f"  Checkpoint: {non_empty}/{total_batches} batches done ({len(completed)-non_empty} empty/failed will retry)")
        except Exception:
            logger.warning("  Checkpoint load failed — starting fresh")

    remaining = [(i, batches[i]) for i in range(total_batches)
                 if i not in completed or not is_valid_batch(completed.get(i, []))]

    ckpt_lock = threading.Lock()

    # ── Process remaining batches concurrently ──────
    if remaining:
        logger.info(
            f"  Remaining: {len(remaining)} batches "
            f"(concurrency={cfg.MAX_CONCURRENT})"
        )

        def make_prompt(item):
            _, batch_df = item
            records = df_to_records(batch_df)
            articles_text = json.dumps(records, ensure_ascii=False, indent=1)
            return (prompt_tpl
                    .replace("{topic}", cfg.TOPIC)
                    .replace("{articles}", articles_text))

        def on_done(flat_idx, result):
            abs_idx = remaining[flat_idx][0]
            with ckpt_lock:
                completed[abs_idx] = result if isinstance(result, list) else []
                save_checkpoint_if_due(completed, checkpoint_path, total_batches)

        llm.concurrent_batch_call(
            items=remaining,
            prompt_fn=make_prompt,
            model=cfg.MODEL_LIGHT,
            desc="A1-Phase1 Summarize",
            max_workers=cfg.MAX_CONCURRENT,
            on_item_done=on_done,
        )

        # Ensure final checkpoint is saved
        save_checkpoint_if_due(completed, checkpoint_path, total_batches, every=1)
    else:
        logger.info("  All batches complete — assembling from checkpoint")

    # ── Micro-retry: re-split persistently-failed batches ──
    still_empty = [i for i in range(total_batches) if not completed.get(i)]
    if still_empty:
        logger.info(
            f"  Micro-retry: {len(still_empty)} still-empty batches → splitting to batch_size=1"
        )
        micro_items = []
        for abs_idx in still_empty:
            for sub_df in chunk_dataframe(batches[abs_idx], 1):
                micro_items.append((abs_idx, sub_df))

        micro_results: dict[int, list] = {i: [] for i in still_empty}

        def make_micro_prompt(item):
            _, sub_df = item
            records = df_to_records(sub_df)
            articles_text = json.dumps(records, ensure_ascii=False, indent=1)
            return (prompt_tpl
                    .replace("{topic}", cfg.TOPIC)
                    .replace("{articles}", articles_text))

        def on_micro_done(flat_idx, result):
            abs_idx, _ = micro_items[flat_idx]
            with ckpt_lock:
                if isinstance(result, list):
                    micro_results[abs_idx].extend(result)

        llm.concurrent_batch_call(
            items=micro_items,
            prompt_fn=make_micro_prompt,
            model=cfg.MODEL_LIGHT,
            desc="A1-Phase1 Micro-retry",
            max_workers=cfg.MAX_CONCURRENT,
            on_item_done=on_micro_done,
        )

        for abs_idx in still_empty:
            completed[abs_idx] = micro_results[abs_idx]

        save_json(
            {"batch_results": {str(k): v for k, v in completed.items()}},
            checkpoint_path,
        )

    # ── Assemble in original order ──────────────────
    all_summaries = []
    for i in range(total_batches):
        batch_result = completed.get(i, [])
        if is_valid_batch(batch_result):
            all_summaries.extend(batch_result)

    if len(all_summaries) < len(df):
        logger.warning(
            f"⚠ A1-P1 count mismatch: {len(df)} articles in, "
            f"{len(all_summaries)} summaries out "
            f"({len(df) - len(all_summaries)} possibly dropped by LLM)"
        )

    out_path = cfg.INTERMEDIATE_DIR / "a1_phase1_summaries.json"
    save_json(all_summaries, out_path)
    logger.info(f"Phase 1 done: {len(all_summaries)} summaries")
    return all_summaries


# ── Phase 2: Cluster into Themes ────────────────────
def phase2_cluster(summaries: list[dict] = None) -> list[dict]:
    """
    Take summaries → embedding-based clustering → LLM labels each cluster.
    Uses code (k-means) for grouping, LLM only for naming themes.
    """
    if summaries is None:
        summaries = read_json(cfg.INTERMEDIATE_DIR / "a1_phase1_summaries.json")

    from utils.clustering import bertopic_cluster, build_cluster_dicts

    pool_n = compute_pool_size(cfg.A1_GENERATE_N, cfg.A1_OVERGEN_FACTOR, cfg.A1_GENERATE_CAP)
    MERGE_TARGET = pool_n
    logger.info(f"A1 over-generation: deliver={cfg.A1_GENERATE_N}, factor={cfg.A1_OVERGEN_FACTOR}, cap={cfg.A1_GENERATE_CAP} -> pool_n={pool_n}")

    summary_texts = [
        (s.get("title_ja") or "") + " " + (s.get("summary_ja") or "")
        for s in summaries
    ]

    logger.info(f"Phase 2: clustering {len(summaries)} summaries into ~{MERGE_TARGET} themes via BERTopic (UMAP+HDBSCAN)")
    clusters, embeddings = bertopic_cluster(
        summary_texts,
        min_cluster_size=cfg.A1_BERTOPIC_MIN_CLUSTER_SIZE,
        target_n_topics=MERGE_TARGET,
        drop_outliers=cfg.A1_BERTOPIC_DROP_OUTLIERS,
        return_embeddings=True,
    )

    # Build cluster dicts with article IDs (directly from k-means — no re-association needed)
    cluster_dicts = build_cluster_dicts(
        clusters, summaries,
        id_field="article_id",
        text_fn=lambda s: (s.get("title_ja") or "") + ": " + (s.get("summary_ja") or "")[:200],
        cluster_id_prefix="T",
        embeddings=embeddings,
    )

    # LLM labels each cluster with a theme name and structural direction
    llm = get_client()
    llm.set_step("A1-cluster")

    label_tpl = load_prompt("a1_phase2_label_themes.txt")

    def make_label_prompt(item):
        cd = item
        rep_text = json.dumps(cd["representative_texts"], ensure_ascii=False, indent=1)
        return (label_tpl
                .replace("{num_articles}", str(len(cd["article_ids"])))
                .replace("{topic}", cfg.TOPIC)
                .replace("{timeframe}", cfg.TIMEFRAME)
                .replace("{representative_texts}", rep_text))

    label_results = llm.concurrent_batch_call(
        items=cluster_dicts,
        prompt_fn=make_label_prompt,
        model=cfg.MODEL_HEAVY,
        desc="A1-Phase2 Label Themes",
        max_workers=cfg.MAX_CONCURRENT,
    )

    # Merge LLM labels back into cluster dicts
    all_themes = []
    for ci, (cd, label) in enumerate(zip(cluster_dicts, label_results)):
        theme = {
            "theme_id": cd["cluster_id"],
            "theme_name_ja": "",
            "structural_direction_ja": "",
            "related_article_ids": cd["article_ids"],
        }
        if isinstance(label, dict):
            theme["theme_name_ja"] = label.get("theme_name_ja", "")
            theme["structural_direction_ja"] = label.get("structural_direction_ja", "")
        elif isinstance(label, list) and label and isinstance(label[0], dict):
            theme["theme_name_ja"] = label[0].get("theme_name_ja", "")
            theme["structural_direction_ja"] = label[0].get("structural_direction_ja", "")
        all_themes.append(theme)

    # Log coverage
    all_input_ids = {str(s.get("article_id", "")) for s in summaries} - {""}
    clustered_ids = set()
    for t in all_themes:
        clustered_ids.update(str(aid) for aid in t.get("related_article_ids", []))
    uncovered = all_input_ids - clustered_ids
    if uncovered:
        logger.warning(f"⚠ A1-Phase2: {len(uncovered)}/{len(all_input_ids)} articles not in any theme")
    else:
        logger.info(f"  Article coverage: all {len(all_input_ids)} articles assigned to themes")

    out_path = cfg.INTERMEDIATE_DIR / "a1_phase2_themes.json"
    save_json(all_themes, out_path)
    logger.info(f"Phase 2 done: {len(all_themes)} themes")
    return all_themes


# ── Phase 3: Generate Scenarios ─────────────────────
def phase3_generate(themes: list[dict] = None) -> list[dict]:
    """
    Take clustered themes → generate one Expected Scenario per theme (concurrent).
    """
    if themes is None:
        themes = read_json(cfg.INTERMEDIATE_DIR / "a1_phase2_themes.json")

    # ── Enrich summaries with row_num for source article injection ──
    enriched_summaries: list[dict] = []
    try:
        raw_summaries = read_json(cfg.INTERMEDIATE_DIR / "a1_phase1_summaries.json")
        row_num_map = _build_row_num_map(cfg.A1_INPUT_FILE)
        for s in raw_summaries:
            aid = str(s.get("article_id", ""))
            info = row_num_map.get(aid)
            if info:
                enriched_summaries.append({**s, "row_num": info["row_num"], "pub_year": info["pub_year"]})
            else:
                enriched_summaries.append(s)
        matched = sum(1 for s in enriched_summaries if s.get("row_num"))
        logger.info(f"  Row-num enrichment: {matched}/{len(enriched_summaries)} summaries mapped")
    except Exception as exc:
        logger.warning(f"  Could not enrich summaries with row_nums: {exc}")

    llm = get_client()
    llm.set_step("A1-generate")
    prompt_tpl = load_prompt("a1_phase3_generate.txt")

    target_industries = ", ".join(cfg.CLIENT_PROFILE["industries"])
    target_industries_ja = ", ".join(f"[{x}]" for x in cfg.CLIENT_PROFILE["industries_ja"])
    total_themes = len(themes)
    themes_signature = _a1_phase3_signature(themes)
    indexed_themes = [(i, t) for i, t in enumerate(themes)]

    # ── Checkpoint ──────────────────────────────────
    checkpoint_path = cfg.INTERMEDIATE_DIR / "a1_phase3_checkpoint.json"
    completed: dict[int, dict] = {}
    if checkpoint_path.exists():
        try:
            ckpt = read_json(checkpoint_path)
            meta = ckpt.get("meta", {}) if isinstance(ckpt, dict) else {}
            saved_sig = meta.get("themes_signature")
            saved_total = meta.get("total_themes")
            if saved_sig != themes_signature or saved_total != total_themes:
                logger.info(
                    "  A1-Phase3 checkpoint is stale (themes changed) - starting fresh"
                )
            else:
                completed = {int(k): v for k, v in ckpt.get("results", {}).items()}
                logger.info(f"  A1-Phase3 checkpoint: {len(completed)}/{total_themes} done")
        except Exception:
            logger.warning("  A1-Phase3 checkpoint load failed — starting fresh")

    remaining = [(i, t) for i, t in indexed_themes if i not in completed]
    logger.info(f"Phase 3 Generate: {total_themes} themes, {len(remaining)} remaining")

    ckpt_lock = threading.Lock()

    def make_prompt(item):
        _, theme = item
        # Inject top-K relevant source articles so the LLM can cite real row numbers
        relevant = (
            _find_relevant_summaries(theme, enriched_summaries, top_k=12)
            if enriched_summaries else []
        )
        theme_payload = {**theme, "sample_source_articles": relevant} if relevant else theme
        return (prompt_tpl
                .replace("{writing_style}", cfg.WRITING_STYLE)
                .replace("{topic}", cfg.TOPIC)
                .replace("{timeframe}", cfg.TIMEFRAME)
                .replace("{num_scenarios}", "1")
                .replace("{target_industries}", target_industries)
                .replace("{target_industries_ja}", target_industries_ja)
                .replace("{themes}", json.dumps([theme_payload], ensure_ascii=False, indent=1)))

    def on_done(flat_idx, result):
        abs_idx = remaining[flat_idx][0]
        with ckpt_lock:
            if result:
                # call_json returns a list; take first item
                item = result[0] if isinstance(result, list) and result else result
                if isinstance(item, dict):
                    completed[abs_idx] = item
            if len(completed) % 5 == 0 or len(completed) == total_themes:
                _save_a1_phase3_checkpoint(
                    checkpoint_path,
                    completed,
                    total_themes,
                    themes_signature,
                )

    if remaining:
        llm.concurrent_batch_call(
            items=remaining,
            prompt_fn=make_prompt,
            model=cfg.MODEL_HEAVY,
            desc="A1-Phase3 Generate",
            max_workers=cfg.MAX_CONCURRENT,
            on_item_done=on_done,
            temperature=0.75,  # Higher temp for creative scenario generation
        )
        _save_a1_phase3_checkpoint(
            checkpoint_path,
            completed,
            total_themes,
            themes_signature,
        )
    else:
        logger.info("  All A1-Phase3 themes complete — assembling from checkpoint")

    scenarios = [completed[i] for i in range(total_themes) if i in completed]
    missing_themes = [i for i in range(total_themes) if i not in completed]
    if missing_themes:
        logger.warning(
            f"⚠ A1-Phase3: {len(missing_themes)}/{total_themes} themes failed to generate scenarios: "
            f"{missing_themes[:10]}{'...' if len(missing_themes) > 10 else ''}"
        )

    # Reassign unique scenario_ids (each concurrent call independently generates "A-1")
    for idx, s in enumerate(scenarios):
        s["scenario_id"] = f"A-{idx + 1}"

    save_json(scenarios, cfg.INTERMEDIATE_DIR / "a1_phase3_scenarios.json")
    logger.info(f"Phase 3 done: {len(scenarios)}/{total_themes} scenarios generated")
    return scenarios


# ── Phase 4: Rank & Select ───────────────────────────
def phase4_rank(scenarios: list[dict] = None) -> list[dict]:
    """Rank scenarios, keep all gate-passing items, then add global review flags."""
    if scenarios is None:
        scenarios = read_json(cfg.INTERMEDIATE_DIR / "a1_phase3_scenarios.json")

    llm = get_openai_client()
    llm.set_step("A1-rank")

    A1_DIMS = ["structural_depth", "irreversibility", "industry_related", "topic_relevance", "feasibility"]

    a1_summary_fn = lambda s: {
        "scenario_id": s.get("scenario_id"),
        "title_ja": s.get("title_ja", ""),
        "change_from_ja": (s.get("change_from_ja") or "")[:300],
        "change_to_ja": (s.get("change_to_ja") or "")[:300],
    }

    scenarios, final = rank_and_select(
        scenarios, A1_DIMS,
        load_prompt("a1_phase4_rank.txt"),
        llm, cfg.RANK_MODEL,
        summary_fn=a1_summary_fn,
        prompt_vars={
            "topic": cfg.TOPIC,
            "target_industries": ", ".join(cfg.CLIENT_PROFILE["industries"]),
        },
        step_label="A1-Phase4",
        weights=cfg.A1_WEIGHTS,
    )

    # Save full ranked pool (over-generated) to intermediate for audit.
    save_json(scenarios, cfg.INTERMEDIATE_DIR / "a1_phase4_ranked.json")

    # Final pick: one LLM call selects K from the pool, balancing score +
    # topic diversity + title uniqueness + topic relevance, and rewrites any
    # title that is too jargony/abstract.
    final = pick_final(
        final, k=cfg.A1_GENERATE_N, llm=llm, model=cfg.RANK_MODEL,
        fields=["title_ja", "change_from_ja", "change_to_ja", "implications_for_company_ja"],
        topic=cfg.TOPIC, step_label="A1-Phase4",
    )

    # Translate and save
    if getattr(cfg, "TRANSLATE_ENABLED", False):
        oai = get_openai_client()
        oai.set_step("A1-translate")
        final = translate_to_zh(final, oai, cfg.TRANSLATE_MODEL)
    save_split(final, cfg.OUTPUT_DIR, "A1_expected_scenarios")

    df = pd.DataFrame([
        {
            "scenario_id": s.get("scenario_id"),
            "total_score": s.get("total_score"),
            "score_structural_depth": s.get("score_structural_depth", 0),
            "score_irreversibility": s.get("score_irreversibility", 0),
            "score_industry_related": s.get("score_industry_related", 0),
            "score_topic_relevance": s.get("score_topic_relevance", 0),
            "score_feasibility": s.get("score_feasibility", 0),
            "title_ja": s.get("title_ja", ""),
            "title_zh": s.get("title_zh", ""),
            "change_from_ja": s.get("change_from_ja", ""),
            "change_from_zh": s.get("change_from_zh", ""),
            "change_to_ja": s.get("change_to_ja", ""),
            "change_to_zh": s.get("change_to_zh", ""),
            "supporting_evidences_ja": "\n".join(s.get("supporting_evidences_ja", [])),
            "supporting_evidences_zh": "\n".join(s.get("supporting_evidences_zh", [])),
            "post_change_scenario_ja": s.get("post_change_scenario_ja", ""),
            "post_change_scenario_zh": s.get("post_change_scenario_zh", ""),
            "implications_for_company_ja": "\n".join(s.get("implications_for_company_ja", [])),
            "implications_for_company_zh": "\n".join(s.get("implications_for_company_zh", [])),
            "ranking_note_ja": s.get("ranking_note_ja", ""),
            "ranking_note_zh": s.get("ranking_note_zh", ""),
        }
        for s in final
    ])
    save_excel(df, cfg.OUTPUT_DIR / "A1_expected_scenarios.xlsx")

    logger.info(f"Phase 4 done: {len(final)} scenarios written to output after gate filter and review")
    return final


# ── Run All ─────────────────────────────────────────
def run(input_file: Path = None) -> list[dict]:
    """Run the complete A-1 pipeline."""
    logger.info("=" * 60)
    logger.info("Step A-1: Expected Scenario Generation")
    logger.info("=" * 60)

    summaries = phase1_summarize(input_file)
    themes = phase2_cluster(summaries)
    scenarios = phase3_generate(themes)
    final = phase4_rank(scenarios)

    logger.info(f"Step A-1 complete: {len(final)} scenarios written to output")
    return final


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
