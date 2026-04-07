"""
Data I/O helpers: read/write CSV, Excel, JSON + batching utilities.
"""
import json
import logging
import os
from pathlib import Path
from typing import Union

import pandas as pd

import config as cfg

logger = logging.getLogger(__name__)


# ── Read ────────────────────────────────────────────
def read_input(path: Union[str, Path], nrows: int = None) -> pd.DataFrame:
    """Read CSV or Excel into DataFrame. Pass nrows to limit rows."""
    path = Path(path)
    if path.suffix == ".csv":
        return pd.read_csv(path, encoding="utf-8-sig", nrows=nrows)
    elif path.suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, nrows=nrows)
    else:
        raise ValueError(f"Unsupported format: {path.suffix}")


def read_json(path: Union[str, Path]) -> Union[dict, list]:
    """Read JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Write ───────────────────────────────────────────
def save_json(data, path: Union[str, Path], indent: int = 2):
    """Save data as JSON (atomic write via temp file)."""
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    logger.info(f"Saved: {path}")


def save_excel(df: pd.DataFrame, path: Union[str, Path], sheet_name: str = "Sheet1"):
    """Save DataFrame as Excel."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False, sheet_name=sheet_name)
    logger.info(f"Saved: {path}")


# ── Checkpoint validation ──────────────────────────
def is_valid_batch(v) -> bool:
    """A valid checkpoint batch is a non-empty list of dicts."""
    return (isinstance(v, list) and len(v) > 0
            and all(isinstance(item, dict) for item in v))


# ── Batching ────────────────────────────────────────
def chunk_list(lst: list, size: int) -> list[list]:
    """Split list into chunks of given size."""
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def chunk_dataframe(df: pd.DataFrame, size: int) -> list[pd.DataFrame]:
    """Split DataFrame into chunks of given size."""
    return [df.iloc[i:i + size] for i in range(0, len(df), size)]


def df_to_records(df: pd.DataFrame) -> list[dict]:
    """Convert DataFrame to list of dicts, converting NaN to None."""
    def _clean(v):
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        try:
            if pd.isna(v):
                return None
        except (ValueError, TypeError):
            pass
        return v
    return [{k: _clean(v) for k, v in row.items()}
            for _, row in df.iterrows()]


# ── Prompt loading ─────────────────────────────────
def load_prompt(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    return (cfg.PROMPTS_DIR / name).read_text(encoding="utf-8")


# ── Ranking utilities ──────────────────────────────
def unwrap_rankings(raw) -> list:
    """Unwrap LLM response (dict or list) to a flat list of ranking dicts."""
    if isinstance(raw, dict):
        if "rankings" in raw and isinstance(raw["rankings"], list):
            return raw["rankings"]
        result = next((v for v in raw.values() if isinstance(v, list)), None)
        return result or []
    return raw if isinstance(raw, list) else []


def apply_scores(
    scenarios: list[dict],
    ranking_list: list[dict],
    dimension_keys: list[str],
    *,
    id_field: str = "scenario_id",
    score_prefix: str = "score_",
) -> int:
    """
    Map ranking results back to scenarios. Returns count of newly scored items.

    dimension_keys: list of dimension names as they appear in the ranking's
        'scores' dict (e.g. ["structural_depth", "irreversibility", ...]).
    Each dimension is written to the scenario as ``{score_prefix}{dim_key}``.
    """
    newly_scored = 0
    score_map = {}
    for r in ranking_list:
        rid = r.get(id_field)
        if rid is not None:
            score_map[rid] = r

    for s in scenarios:
        sid = s.get(id_field)
        if sid not in score_map:
            continue
        r = score_map[sid]
        if s.get("total_score", 0) == 0:
            newly_scored += 1
        s["total_score"] = r.get("total_score", 0)
        s["ranking_note_ja"] = r.get("ranking_note_ja", "")
        s["duplicate_of"] = r.get("duplicate_of")
        dims = r.get("scores", {})
        for dk in dimension_keys:
            # Some prompts return base keys in `scores` (e.g. plausibility),
            # while downstream expects *_score fields. Support both forms.
            val = dims.get(dk, r.get(dk))
            if val is None and dk.endswith("_score"):
                base_key = dk[:-6]  # strip "_score"
                val = dims.get(base_key, r.get(base_key, 0))
            if val is None:
                val = 0

            # If key already includes *_score, avoid adding another score_ prefix.
            out_key = dk if (score_prefix == "score_" and dk.endswith("_score")) else f"{score_prefix}{dk}"
            s[out_key] = val
    return newly_scored


# ── Checkpoint helpers ─────────────────────────────
def save_checkpoint_if_due(
    completed: dict,
    checkpoint_path: Union[str, Path],
    total_batches: int,
    *,
    every: int = 10,
    record_key: str = "batch_results",
):
    """Save checkpoint when batch count hits a multiple of `every` or is the last batch."""
    if len(completed) % every == 0 or len(completed) == total_batches:
        save_json(
            {record_key: {str(k): v for k, v in completed.items()}},
            checkpoint_path,
        )


def rank_and_select(
    scenarios: list[dict],
    dims: list[str],
    prompt_tpl: str,
    llm,
    model: str,
    *,
    summary_fn,
    prompt_vars: dict[str, str] | None = None,
    batch_size: int = 30,
    step_label: str = "Rank",
    min_dim_scores: dict[str, int] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Shared ranking pipeline: batch score → global sort → gate filter.

    Returns (all_scenarios_sorted, filtered_selected).
    - summary_fn(scenario) -> dict: produces a condensed summary for the scoring prompt
    - prompt_vars: extra {key: value} replacements for prompt_tpl
    - min_dim_scores: per-dimension minimum scores (scenarios below any threshold are dropped)
    """
    summaries = [summary_fn(s) for s in scenarios]
    batches = chunk_list(summaries, batch_size)

    logger.info(
        f"{step_label}: scoring {len(scenarios)} scenarios in {len(batches)} batches of ≤{batch_size}"
    )

    for bi, batch in enumerate(batches):
        prompt = prompt_tpl.replace("{scenarios}", json.dumps(batch, ensure_ascii=False, indent=1))
        for k, v in (prompt_vars or {}).items():
            prompt = prompt.replace(f"{{{k}}}", v)
        try:
            raw = llm.call_json(prompt, model=model, temperature=0.25, max_tokens=16384)
            batch_rankings = unwrap_rankings(raw)
            if not batch_rankings:
                logger.warning(f"  Batch {bi+1}/{len(batches)}: empty ranking output")
                continue
            apply_scores(scenarios, batch_rankings, dims)
            logger.info(f"  Batch {bi+1}/{len(batches)}: scored {len(batch_rankings)} scenarios")
        except Exception as e:
            logger.error(f"  Batch {bi+1}/{len(batches)} failed: {e}")

    # Global sort by total_score, tiebreak by dimension score variance
    # (higher variance = more distinctive profile = preferred over flat scores)
    def _sort_key(s):
        total = s.get("total_score", 0)
        dim_scores = [s.get(d if d.endswith("_score") else f"score_{d}", 0) for d in dims]
        if len(dim_scores) > 1:
            mean = sum(dim_scores) / len(dim_scores)
            variance = sum((x - mean) ** 2 for x in dim_scores) / len(dim_scores)
        else:
            variance = 0
        return (total, variance)

    scenarios.sort(key=_sort_key, reverse=True)

    # Filter by minimum per-dimension scores
    if min_dim_scores:
        def passes_gate(s):
            for dim_key, min_val in min_dim_scores.items():
                if s.get(dim_key, 0) < min_val:
                    return False
            return True
        before = len(scenarios)
        selected = [s for s in scenarios if passes_gate(s)]
        dropped = before - len(selected)
        if dropped:
            logger.info(f"{step_label}: {dropped} scenarios below dimension thresholds, {len(selected)} remain")
    else:
        selected = list(scenarios)

    scored = [s for s in selected if s.get("total_score", 0) > 0]
    if not scored:
        logger.warning(f"{step_label} failed — using generation order as fallback")
        scored = selected

    logger.info(f"{step_label}: {len(scored)} scored scenarios passed gate filter")
    return scenarios, scored


def enforce_gate(
    scenarios: list[dict],
    min_dim_scores: dict[str, int] | None,
    *,
    step_label: str = "Gate",
) -> list[dict]:
    """
    Final safety-net: remove any scenarios that violate dimension thresholds.
    Should be called just before saving output to catch any leaks from
    upstream steps (llm_review, manual edits, backup restores, etc.).
    """
    if not min_dim_scores:
        return scenarios
    before = len(scenarios)
    kept = [
        s for s in scenarios
        if all(s.get(dim, 0) >= minv for dim, minv in min_dim_scores.items())
    ]
    dropped = before - len(kept)
    if dropped:
        kept_ids = {id(s) for s in kept}
        ids = [s.get("scenario_id") or s.get("signal_id") for s in scenarios if id(s) not in kept_ids]
        logger.warning(
            f"{step_label} enforce_gate: dropped {dropped} scenarios below thresholds: {ids}"
        )
    else:
        logger.info(f"{step_label} enforce_gate: all {before} scenarios pass")
    return kept


def llm_review(
    scenarios: list[dict],
    llm,
    model: str,
    *,
    step: str,
    summary_fn,
    prompt_vars: dict[str, str] | None = None,
    step_label: str = "Review",
) -> list[dict]:
    """
    LLM-based global review: send all scored scenarios to LLM for cross-scenario
    comparison. Flags duplicates, theme overlaps, and step-specific quality issues.

    Mutates scenarios in-place by adding review flags. Returns the same list.

    Args:
        scenarios: list of scenario dicts (already scored and gate-filtered)
        llm: OpenAI client instance with call_json method
        model: model name for the review call
        step: one of "A1", "C", "D" — determines which flags are checked
        summary_fn: produces a condensed dict for each scenario
        prompt_vars: extra {key: value} replacements for the review prompt
    """
    if not scenarios:
        return scenarios

    review_prompt_tpl = load_prompt("review_scenarios.txt")

    summaries = [summary_fn(s) for s in scenarios]
    prompt = review_prompt_tpl.replace(
        "{scenarios}", json.dumps(summaries, ensure_ascii=False, indent=1)
    )
    prompt = prompt.replace("{step}", step)
    for k, v in (prompt_vars or {}).items():
        prompt = prompt.replace(f"{{{k}}}", v)

    logger.info(f"{step_label}: reviewing {len(scenarios)} scenarios globally")

    try:
        raw = llm.call_json(prompt, model=model, temperature=0.2, max_tokens=16384)
        reviews = raw if isinstance(raw, list) else raw.get("reviews", [])

        review_map = {}
        for r in reviews:
            rid = r.get("scenario_id")
            if rid:
                review_map[rid] = r

        flagged = 0
        for s in scenarios:
            sid = s.get("scenario_id")
            if sid not in review_map:
                continue
            r = review_map[sid]
            # Apply flags based on step
            if r.get("duplicate_of"):
                s["review_duplicate_of"] = r["duplicate_of"]
                flagged += 1
            if r.get("theme_overlap"):
                s["review_theme_overlap"] = r["theme_overlap"]
                flagged += 1
            if r.get("weak_source"):
                s["review_weak_source"] = True
                flagged += 1
            if r.get("weak_logic"):
                s["review_weak_logic"] = True
                flagged += 1
            if r.get("weak_collision"):
                s["review_weak_collision"] = True
                flagged += 1
            if r.get("review_note"):
                s["review_note"] = r["review_note"]

        logger.info(f"{step_label}: review complete, {flagged} flags raised across {len(scenarios)} scenarios")

    except Exception as e:
        logger.warning(f"{step_label}: LLM review failed ({e}), skipping review flags")

    return scenarios
