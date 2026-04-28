"""
Data I/O helpers: read/write CSV, Excel, JSON + batching utilities.
"""
from __future__ import annotations

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
    weights: dict[str, float] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Shared ranking pipeline: batch score → compute weighted_score → sort.

    Returns (all_scenarios_sorted, all_scenarios_sorted) — no filter, both lists identical
    (tuple kept for API compat with older callers that destructure).

    - summary_fn(scenario) -> dict: produces a condensed summary for the scoring prompt
    - prompt_vars: extra {key: value} replacements for prompt_tpl
    - weights: per-dimension weight (0-5, default 1 each). weighted_score = Σ weight × raw_score.
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

    # Compute weighted_score for each scenario; sort by it desc.
    # weights acts as an allow-list: dims not in `weights` are still scored by the LLM
    # and stored on the scenario, but do NOT contribute to weighted_score. This lets
    # callers keep purely-reference dims out of ranking if they ever need to.
    w = weights or {}
    def _score_key(d):
        return d if d.endswith("_score") else f"score_{d}"
    weighted_dims = [d for d in dims if d in w]
    for s in scenarios:
        wsum = 0.0
        for d in weighted_dims:
            raw = s.get(_score_key(d), 0) or 0
            wsum += w[d] * raw
        s["weighted_score"] = wsum

    # If every weighted dim has weight 0 (or no dim is weighted), weighted_score is
    # meaningless; fall back to total_score.
    all_zero = not weighted_dims or all(w[d] == 0 for d in weighted_dims)
    if all_zero:
        logger.warning(
            f"{step_label}: all dimension weights are 0 — falling back to total_score for ranking"
        )
        scenarios.sort(key=lambda s: s.get("total_score", 0), reverse=True)
    else:
        scenarios.sort(key=lambda s: s.get("weighted_score", 0), reverse=True)

    # No filter — ranking only. Keep scenarios with non-zero scores ahead of un-scored ones.
    scored = [s for s in scenarios if s.get("total_score", 0) > 0 or s.get("weighted_score", 0) > 0]
    if not scored:
        logger.warning(f"{step_label} failed — using generation order as fallback")
        scored = list(scenarios)

    logger.info(f"{step_label}: {len(scored)} scenarios ranked by weighted_score")
    return scenarios, scored


def compute_pool_size(deliver_n: int, factor: float, cap: int) -> int:
    """How many candidates to actually generate so we can later pick diverse top-K.
    Caps at `cap` so a large client-facing deliver_n cannot blow the API budget.
    """
    deliver_n = max(1, int(deliver_n or 0))
    factor = max(1.0, float(factor or 1.0))
    cap = max(deliver_n, int(cap or deliver_n))
    return min(int(deliver_n * factor), cap)


def pick_final(
    scenarios: list[dict],
    k: int,
    llm,
    model: str,
    *,
    fields: list[str],
    topic: str = "",
    id_field: str = "scenario_id",
    title_keys: tuple = ("title_ja", "title", "opportunity_title_ja", "opportunity_title"),
    step_label: str = "Pick",
) -> list[dict]:
    """Single LLM call: pick K from ranked scenarios, rewrite bad titles in place.

    Replaces the old check_diversity + select_diverse_topk pair. The picker judges
    score, diversity, duplicate titles, and topic relevance in one shot, and
    optionally rewrites titles that are too jargony/abstract.
    """
    if not scenarios:
        return []
    if k >= len(scenarios):
        return list(scenarios)

    # Find which title key each scenario actually has, so we can round-trip
    def _title_of(s):
        for tk in title_keys:
            v = s.get(tk)
            if isinstance(v, str) and v.strip():
                return tk, v
        return None, ""

    # For diversity judgment the LLM needs enough body text to detect "same core
    # idea" underneath different titles. First field (usually the primary narrative
    # like overview / change_from / collision_insight) gets the widest budget.
    items = []
    for s in scenarios:
        tk, title = _title_of(s)
        entry = {
            "id": s.get(id_field, ""),
            "weighted_score": round(s.get("weighted_score", 0) or 0, 1),
            "title": title,
        }
        for idx, f in enumerate(fields):
            v = s.get(f)
            # Give the primary narrative field (index 1 — first non-title field)
            # a larger budget so the picker can compare full premises.
            char_budget = 600 if idx <= 1 else 300
            if isinstance(v, str) and v:
                entry[f] = v[:char_budget]
            elif isinstance(v, list):
                entry[f] = "; ".join(str(x)[:120] for x in v[:3])
        items.append(entry)

    import json as _json
    prompt = load_prompt("pick_final.txt")
    prompt = (prompt
              .replace("{k}", str(k))
              .replace("{topic}", topic or "")
              .replace("{scenarios}", _json.dumps(items, ensure_ascii=False, indent=1)))

    try:
        raw = llm.call_json(prompt, model=model, temperature=0.2, max_tokens=16384)
        if not isinstance(raw, dict):
            raise ValueError(f"picker returned non-dict: {type(raw).__name__}")
        selected = raw.get("selected") or []
        if not isinstance(selected, list) or not selected:
            raise ValueError("picker: 'selected' empty or not a list")

        by_id = {str(s.get(id_field, "")): s for s in scenarios}
        final = []
        seen = set()
        for entry in selected:
            if not isinstance(entry, dict):
                continue
            sid = str(entry.get("id", ""))
            if not sid or sid in seen:
                continue
            s = by_id.get(sid)
            if s is None:
                logger.warning(f"{step_label}: picker referenced unknown id {sid!r}, skipping")
                continue
            title_new = (entry.get("title_new") or "").strip()
            if title_new:
                tk, old_title = _title_of(s)
                if tk and title_new != old_title:
                    s.setdefault("title_original", old_title)
                    s[tk] = title_new
                    logger.info(f"{step_label}: {sid} title rewritten -> {title_new}")
            final.append(s)
            seen.add(sid)

        if not final:
            raise ValueError("picker returned no valid ids")
        logger.info(f"{step_label}: picker selected {len(final)} from {len(scenarios)} candidates")
        return final
    except Exception as e:
        logger.warning(f"{step_label}: picker failed ({e}), falling back to top-K by weighted_score")
        ranked = sorted(scenarios, key=lambda s: -(s.get("weighted_score", 0) or 0))
        return ranked[:k]


