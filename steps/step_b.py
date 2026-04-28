"""
Step B: Weak Signal Selection
=============================
Weak signals → batch score (3 dims) → rank → TOP N → diversity dedup → final selection
"""
import json
import logging
import threading
import hashlib
from pathlib import Path

import pandas as pd

import config as cfg
from utils.openai_client import get_openai_client
from utils.data_io import (
    read_input, read_json, save_json, save_excel,
    chunk_dataframe, df_to_records, chunk_list, is_valid_batch,
    load_prompt,
)
from utils.bilingual import save_split, translate_to_zh

logger = logging.getLogger(__name__)


def _b_score_signature(
    *,
    input_file: Path,
    input_rows: int,
    prompt_tpl: str,
) -> str:
    """Hash all inputs that affect B-score prompt outputs. A1 is NOT included:
    B scoring is independent of A1 by design (outside_area = outside industry)."""
    cp = getattr(cfg, "CLIENT_PROFILE", {}) or {}
    try:
        input_mtime = input_file.stat().st_mtime
    except OSError:
        input_mtime = None

    payload = {
        "topic": str(getattr(cfg, "TOPIC", "") or ""),
        "timeframe": str(getattr(cfg, "TIMEFRAME", "") or ""),
        "client_profile": {
            "name": str(cp.get("name", "") or ""),
            "industries": [str(x) for x in (cp.get("industries") or [])],
            "known_domains": [str(x) for x in (cp.get("known_domains") or [])],
            "description": str(cp.get("description", "") or ""),
        },
        "input_file": str(input_file),
        "input_rows": int(input_rows),
        "input_mtime": input_mtime,
        "prompt_hash": hashlib.sha1(prompt_tpl.encode("utf-8")).hexdigest(),
        "model": str(getattr(cfg, "B_MODEL_SCORE", "") or ""),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _save_b_score_checkpoint(
    checkpoint_path: Path,
    completed: dict[int, list],
    total_batches: int,
    score_signature: str,
):
    save_json(
        {
            "meta": {
                "total_batches": total_batches,
                "score_signature": score_signature,
            },
            "batch_results": {str(k): v for k, v in completed.items()},
        },
        checkpoint_path,
    )


def _build_client_profile_text() -> str:
    cp = cfg.CLIENT_PROFILE
    return (
        f"企業名: {cp['name']}\n"
        f"主要産業: {', '.join(cp['industries'])}\n"
        f"既知領域: {', '.join(cp['known_domains'])}\n"
        f"概要: {cp['description']}"
    )


def _looks_like_scored_signal(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    return any(
        k in item
        for k in ("signal_id", "title_ja", "title", "scores", "total_score")
    )


def _extract_scored_signals(payload) -> list[dict]:
    """Best-effort extraction for scored signal arrays from JSON-object outputs."""
    if isinstance(payload, list):
        return payload if all(isinstance(x, dict) for x in payload) else []
    if not isinstance(payload, dict):
        return []

    # Preferred top-level keys.
    for key in ("signals", "results", "scored", "rankings", "items"):
        value = payload.get(key)
        if isinstance(value, list) and all(isinstance(x, dict) for x in value):
            return value

    # Common wrapper shapes, e.g. {"data": {"signals": [...]}}
    for key in ("data", "output", "response"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            extracted = _extract_scored_signals(nested)
            if extracted:
                return extracted

    # Sometimes the model returns a dict keyed by signal_id.
    dict_values = list(payload.values())
    if dict_values and all(isinstance(v, dict) for v in dict_values):
        if all(_looks_like_scored_signal(v) for v in dict_values):
            return dict_values

    # Last resort: search nested dicts for first plausible list[dict].
    stack = [payload]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        cur_id = id(cur)
        if cur_id in seen:
            continue
        seen.add(cur_id)

        if isinstance(cur, dict):
            for value in cur.values():
                if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                    if any(_looks_like_scored_signal(x) for x in value):
                        return value
                elif isinstance(value, dict):
                    stack.append(value)

    return []


def score_signals(
    input_file: Path = None,
) -> list[dict]:
    """Phase 1: Score all weak signals in batches on 3 dimensions."""
    input_file = input_file or cfg.B_INPUT_FILE
    llm = get_openai_client()
    llm.set_step("B-score")
    prompt_tpl = load_prompt("b_phase1_score_signals.txt")

    nrows = cfg.SMOKE_ROWS if cfg.SMOKE_TEST else None
    logger.info(f"Loading weak signals from {input_file}" + (" [SMOKE TEST]" if nrows else ""))
    df = read_input(input_file, nrows=nrows)
    logger.info(f"  Total signals: {len(df)}")

    batches = chunk_dataframe(df, cfg.B_BATCH_SIZE)
    total_batches = len(batches)
    logger.info(f"  Batches: {total_batches} x {cfg.B_BATCH_SIZE}")
    score_signature = _b_score_signature(
        input_file=input_file,
        input_rows=len(df),
        prompt_tpl=prompt_tpl,
    )

    # ── Checkpoint ──────────────────────────────────
    checkpoint_path = cfg.INTERMEDIATE_DIR / "b_phase1_checkpoint.json"
    completed: dict[int, list] = {}
    if checkpoint_path.exists():
        try:
            ckpt = read_json(checkpoint_path)
            meta = ckpt.get("meta", {}) if isinstance(ckpt, dict) else {}
            saved_sig = meta.get("score_signature")
            saved_total = meta.get("total_batches")
            if saved_sig != score_signature or saved_total != total_batches:
                logger.info("  B-score checkpoint is stale (prompt/context changed) - starting fresh")
            else:
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
                .replace("{known_domains}", ", ".join(cfg.CLIENT_PROFILE["known_domains"]))
                .replace("{signals}", signals_text))

    def on_done(flat_idx, result):
        abs_idx = remaining[flat_idx][0]
        with ckpt_lock:
            extracted = _extract_scored_signals(result)
            if extracted:
                completed[abs_idx] = extracted
            else:
                if isinstance(result, dict):
                    logger.warning(
                        f"  Batch {abs_idx}: unable to extract scored signals, top-level keys={list(result.keys())}"
                    )
                elif result is None:
                    logger.warning(f"  Batch {abs_idx}: LLM returned None")
                else:
                    logger.warning(f"  Batch {abs_idx}: unexpected LLM result type={type(result).__name__}")
                completed[abs_idx] = []
            if len(completed) % 10 == 0 or len(completed) == total_batches:
                _save_b_score_checkpoint(
                    checkpoint_path,
                    completed,
                    total_batches,
                    score_signature,
                )

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
        _save_b_score_checkpoint(
            checkpoint_path,
            completed,
            total_batches,
            score_signature,
        )
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


def diversity_dedup(candidates: list[dict] = None) -> list[dict]:
    """
    Phase 2: Rank by total_score, take top N*1.5 candidates, then remove
    near-duplicates via batched LLM diversity check. Signals not mentioned
    by the LLM are kept (treat-as-unique).
    """
    if candidates is None:
        scored = read_json(cfg.INTERMEDIATE_DIR / "b_phase1_scored.json")
        valid = [s for s in scored if s and "scores" in s]
        weights = cfg.B_WEIGHTS
        for s in valid:
            dims = s.get("scores", {}) or {}
            s["total_score"] = float(sum(weights.get(k, 0) * float(v) for k, v in dims.items()))
            # Write per-dim scores under both bare and "score_"-prefixed names so
            # downstream callers (rank_and_select, validate_output, xlsx export)
            # find them under whichever convention they expect.
            for dim, val in dims.items():
                s.setdefault(dim, val)
                s.setdefault(f"score_{dim}", val)
        valid.sort(key=lambda x: x["total_score"], reverse=True)
        candidates = valid[:int(cfg.B_TOP_N * 1.5)]
        logger.info(
            f"Ranked {len(valid)} scored signals with weights {weights}, took top {len(candidates)} for diversity check"
        )

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
    # Sidecar so downstream can detect topic-mismatch and force re-run.
    cp = getattr(cfg, "CLIENT_PROFILE", {}) or {}
    save_json(
        {
            "topic": cfg.TOPIC,
            "timeframe": cfg.TIMEFRAME,
            "industries": [str(x) for x in (cp.get("industries") or [])],
            "n": len(final),
        },
        cfg.INTERMEDIATE_DIR / "b_phase3_dedup_selected.meta.json",
    )
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
    """Run complete Step B: Score -> Rank + Diversity Dedup."""
    logger.info("=" * 60)
    logger.info("Step B: Weak Signal Selection (2-phase)")
    logger.info("=" * 60)

    score_signals(input_file)
    selected = diversity_dedup()

    logger.info(f"Step B complete: {len(selected)} signals selected")
    return selected


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
