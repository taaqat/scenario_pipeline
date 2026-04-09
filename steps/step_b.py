"""
Step B: Weak Signal Selection
=============================
Weak signals → batch score (4 dims) → rank → TOP N → diversity dedup → final selection
"""
import json
import logging
import threading
from pathlib import Path

import pandas as pd

import config as cfg
from utils.openai_client import get_openai_client
from utils.data_io import (
    read_input, read_json, save_json, save_excel,
    chunk_dataframe, df_to_records, chunk_list, is_valid_batch,
    load_prompt, save_checkpoint_if_due, enforce_gate,
)
from utils.bilingual import save_split, translate_to_zh

logger = logging.getLogger(__name__)


def _build_client_profile_text() -> str:
    cp = cfg.CLIENT_PROFILE
    return (
        f"企業名: {cp['name']}\n"
        f"主要産業: {', '.join(cp['industries'])}\n"
        f"既知領域: {', '.join(cp['known_domains'])}\n"
        f"概要: {cp['description']}"
    )


def score_signals(
    input_file: Path = None,
    expected_scenarios: list[dict] = None,
) -> list[dict]:
    """Phase 1: Score all weak signals in batches on 4 dimensions."""
    input_file = input_file or cfg.B_INPUT_FILE
    llm = get_openai_client()
    llm.set_step("B-score")
    prompt_tpl = load_prompt("b_phase1_score_signals.txt")

    nrows = cfg.SMOKE_ROWS if cfg.SMOKE_TEST else None
    logger.info(f"Loading weak signals from {input_file}" + (" [SMOKE TEST]" if nrows else ""))
    df = read_input(input_file, nrows=nrows)
    logger.info(f"  Total signals: {len(df)}")

    # Load A-1 results for exclusion
    if expected_scenarios is None:
        a1_path = cfg.INTERMEDIATE_DIR / "a1_phase3_scenarios.json"
        if a1_path.exists():
            expected_scenarios = read_json(a1_path)
        else:
            logger.warning("A-1 results not found — scoring without exclusion context")
            expected_scenarios = []

    expected_themes = json.dumps(
        [{"id": s.get("scenario_id"),
          "title": s.get("title_ja", s.get("title", ""))}
         for s in expected_scenarios],
        ensure_ascii=False
    )

    batches = chunk_dataframe(df, cfg.B_BATCH_SIZE)
    total_batches = len(batches)
    logger.info(f"  Batches: {total_batches} x {cfg.B_BATCH_SIZE}")

    # ── Checkpoint ──────────────────────────────────
    checkpoint_path = cfg.INTERMEDIATE_DIR / "b_phase1_checkpoint.json"
    completed: dict[int, list] = {}
    if checkpoint_path.exists():
        try:
            ckpt = read_json(checkpoint_path)
            completed = {int(k): v for k, v in ckpt.get("batch_results", {}).items()}
            non_empty = sum(1 for v in completed.values() if v)
            logger.info(f"  B-score checkpoint: {non_empty}/{total_batches} batches done ({total_batches - non_empty} remaining)")
        except Exception:
            logger.warning("  B-score checkpoint load failed — starting fresh")

    remaining = [(i, batches[i]) for i in range(total_batches)
                 if i not in completed or not is_valid_batch(completed.get(i, []))]

    client_profile = _build_client_profile_text()
    ckpt_lock = threading.Lock()

    def make_prompt(item):
        _, batch_df = item
        records = df_to_records(batch_df)
        signals_text = json.dumps(records, ensure_ascii=False, indent=1)
        return (prompt_tpl
                .replace("{topic}", cfg.TOPIC)
                .replace("{client_profile}", client_profile)
                .replace("{expected_themes}", expected_themes)
                .replace("{known_domains}", ", ".join(cfg.CLIENT_PROFILE["known_domains"]))
                .replace("{signals}", signals_text))

    def on_done(flat_idx, result):
        abs_idx = remaining[flat_idx][0]
        with ckpt_lock:
            if isinstance(result, list):
                completed[abs_idx] = result
            elif isinstance(result, dict):
                # OpenAI json_object mode wraps arrays — extract the first list value
                extracted = next((v for v in result.values() if isinstance(v, list)), None)
                if extracted is None:
                    logger.warning(f"  Batch {abs_idx}: LLM returned dict without list value, keys={list(result.keys())}")
                    extracted = []
                completed[abs_idx] = extracted
            else:
                completed[abs_idx] = []
            save_checkpoint_if_due(completed, checkpoint_path, total_batches)

    if remaining:
        logger.info(f"  Scoring {len(remaining)} remaining batches...")
        llm.concurrent_batch_call(
            items=remaining,
            prompt_fn=make_prompt,
            model=cfg.B_MODEL_SCORE,
            desc="B-Score",
            max_workers=cfg.MAX_CONCURRENT,
            on_item_done=on_done,
            temperature=0.3,  # Low temp for consistent scoring
            max_tokens=16384,  # 確保 output 不被截斷
        )
        save_checkpoint_if_due(completed, checkpoint_path, total_batches, every=1)
    else:
        logger.info("  All B-score batches complete — assembling from checkpoint")

    all_scored = []
    for i in range(total_batches):
        r = completed.get(i, [])
        if is_valid_batch(r):
            all_scored.extend(r)

    # Coverage check only (no second scoring pass)
    INPUT_ID_COL = "JRI ID"  # column name in the original Excel
    final_scored_ids = {str(s.get("signal_id", "")).strip() for s in all_scored if s}
    all_records = df_to_records(df)
    all_input_ids = {str(r.get(INPUT_ID_COL, "")).strip() for r in all_records}
    uncovered_ids = all_input_ids - final_scored_ids - {""}
    if uncovered_ids:
        logger.warning(
            f"⚠ B-P1 coverage: {len(all_input_ids)} input signals, "
            f"{len(final_scored_ids)} scored, {len(uncovered_ids)} missing. "
            f"No retry by design (single-stage scoring). Missing IDs (first 20): {sorted(uncovered_ids)[:20]}"
        )
    else:
        logger.info(f"✓ B-P1 all {len(all_input_ids)} signals scored successfully (single-stage)")

    save_json(all_scored, cfg.INTERMEDIATE_DIR / "b_phase1_scored.json")
    logger.info(f"Phase 1 scored: {len(all_scored)} signals")
    return all_scored


def select_top_signals(scored: list[dict] = None) -> list[dict]:
    """Phase 2: Rank by total_score, pick top N * 1.5 candidates."""
    if scored is None:
        scored = read_json(cfg.INTERMEDIATE_DIR / "b_phase1_scored.json")

    valid = [s for s in scored if s and "total_score" in s]
    logger.info(f"Valid scored signals: {len(valid)}")

    # Ensure total_score is numeric (LLM sometimes returns strings)
    for s in valid:
        try:
            s["total_score"] = float(s["total_score"])
        except (ValueError, TypeError):
            s["total_score"] = 0.0
    valid.sort(key=lambda x: x["total_score"], reverse=True)

    # Flatten nested scores to top-level for enforce_gate compatibility
    for s in valid:
        for dim, val in s.get("scores", {}).items():
            s.setdefault(dim, val)

    valid = enforce_gate(valid, cfg.B_MIN_DIM_SCORES, step_label="B-Phase2")

    # Take extra — diversity check will trim
    candidates = valid[:int(cfg.B_TOP_N * 1.5)]

    save_json(candidates, cfg.INTERMEDIATE_DIR / "b_phase2_top3000_candidates.json")
    logger.info(f"Phase 2: top {len(candidates)} candidates for diversity check")
    return candidates


def diversity_dedup(candidates: list[dict] = None) -> list[dict]:
    """
    Phase 3: Remove near-duplicate signals via batched LLM diversity check.
    Splits candidates into B_DIVERSITY_BATCH-sized chunks so the LLM can
    process all signals (avoids output truncation on large inputs).
    Signals not mentioned by the LLM are kept (treat-as-unique approach).
    """
    if candidates is None:
        top3000_path = cfg.INTERMEDIATE_DIR / "b_phase2_top3000_candidates.json"
        legacy_path = cfg.INTERMEDIATE_DIR / "b_phase2_top2000_candidates.json"
        candidates = read_json(top3000_path if top3000_path.exists() else legacy_path)

    llm = get_openai_client()
    llm.set_step("B-diversity")
    prompt_tpl = load_prompt("b_phase3_diversity_check.txt")

    # Split into manageable batches so each call stays within output token limits
    batches = chunk_list(candidates, cfg.B_DIVERSITY_BATCH)
    total_batches = len(batches)
    logger.info(f"Phase 3: diversity check — {len(candidates)} candidates in {total_batches} batches of ≤{cfg.B_DIVERSITY_BATCH}")

    indexed_batches = list(enumerate(batches))

    def make_prompt(item):
        _, batch = item
        summaries = [
            {"signal_id": s.get("signal_id"),
             "title_ja": s.get("title_ja", s.get("title", "")),
             "total_score": s.get("total_score")}
            for s in batch
        ]
        return (prompt_tpl
                .replace("{count}", str(len(summaries)))
                .replace("{topic}", cfg.TOPIC)
                .replace("{signals_json}", json.dumps(summaries, ensure_ascii=False, indent=1)))

    results = llm.concurrent_batch_call(
        items=indexed_batches,
        prompt_fn=make_prompt,
        model=cfg.B_MODEL_DIVERSITY,
        desc="B-Diversity",
        max_workers=cfg.MAX_CONCURRENT,
        max_tokens=8000,
    )

    # Collect drop_ids: within each cluster, drop all but keep_id
    all_drop_ids: set[str] = set()
    for result in results:
        if result and "clusters" in result:
            for cluster in result.get("clusters", []):
                keep_id = str(cluster.get("keep_id", ""))
                for sid in cluster.get("signal_ids", []):
                    if str(sid) != keep_id:
                        all_drop_ids.add(str(sid))

    deduped = [s for s in candidates if str(s.get("signal_id")) not in all_drop_ids]
    save_json({"total_dropped": len(all_drop_ids)},
              cfg.INTERMEDIATE_DIR / "b_phase3_dedup_summary.json")
    logger.info(
        f"Phase 3: removed {len(all_drop_ids)} duplicates across {total_batches} batches, "
        f"keeping {len(deduped)} (of {len(candidates)})"
    )

    # Final trim
    final = deduped[:cfg.B_TOP_N]

    # Translate and save bilingual split
    if getattr(cfg, "TRANSLATE_ENABLED", False):
        llm.set_step("B-translate")
        final = translate_to_zh(final, llm, cfg.TRANSLATE_MODEL, batch_size=20)
    save_json(final, cfg.INTERMEDIATE_DIR / "b_phase3_dedup_selected.json")
    save_split(final, cfg.OUTPUT_DIR, "B_selected_weak_signals")

    # Excel for human review
    df = pd.DataFrame([
        {
            "signal_id": s.get("signal_id"),
            "title_ja": s.get("title_ja", s.get("title", "")),
            "title_zh": s.get("title_zh", ""),
            "total_score": s.get("total_score"),
            **s.get("scores", {}),
            "reasoning_ja": s.get("reasoning_ja", s.get("reasoning", "")),
            "reasoning_zh": s.get("reasoning_zh", ""),
        }
        for s in final
    ])
    save_excel(df, cfg.OUTPUT_DIR / "B_selected_weak_signals.xlsx")

    logger.info(f"Phase 3 complete: {len(final)} signals selected")
    return final


# ── Run All ─────────────────────────────────────────
def run(input_file: Path = None) -> list[dict]:
    """Run complete Step B: Score -> Rank -> Diversity Dedup."""
    logger.info("=" * 60)
    logger.info("Step B: Weak Signal Selection (3-phase)")
    logger.info("=" * 60)

    scored = score_signals(input_file)
    candidates = select_top_signals(scored)
    selected = diversity_dedup(candidates)

    logger.info(f"Step B complete: {len(selected)} signals selected")
    return selected


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
