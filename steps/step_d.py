"""
Step D: Opportunity Scenario Synthesis
======================================
Two modes (cfg.D_MODE):
    "hybrid" — Phase 1: Smart pair selection → Phase 2: Generate → Phase 3: Rank, gate filter, review
    "matrix" — All A×C pairs → Phase 2: Generate all → Phase 3: Rank, gate filter, review
Phase 2: Generate full scenarios for selected pairs
Phase 3: Rank, gate filter, and review all candidates
"""
import json
import logging
import threading
import hashlib
from itertools import product
from pathlib import Path

import pandas as pd

import config as cfg
from utils.llm_client import get_client
from utils.openai_client import get_openai_client
from utils.data_io import (
    read_json, save_json, save_excel, chunk_list,
    load_prompt, unwrap_rankings, apply_scores, save_checkpoint_if_due,
    rank_and_select, pick_final,
    compute_pool_size,
)
from utils.bilingual import save_split, translate_to_zh, strip_zh

logger = logging.getLogger(__name__)


def _d_pool_n() -> int:
    return compute_pool_size(cfg.D_GENERATE_N, cfg.D_OVERGEN_FACTOR, cfg.D_GENERATE_CAP)


def _d_phase2_signature(pairs: list[dict]) -> str:
    """Build a stable signature for D-Phase2 inputs + runtime context."""
    compact_pairs = [
        {
            "pair_id": str(p.get("pair_id", i + 1)),
            "expected_ids": [str(aid) for aid in p.get("expected_ids", [])],
            "unexpected_ids": [str(cid) for cid in p.get("unexpected_ids", [])],
            "generation_mode": str(p.get("generation_mode", "")),
        }
        for i, p in enumerate(pairs)
    ]
    cp = getattr(cfg, "CLIENT_PROFILE", {}) or {}
    context = {
        "topic": str(getattr(cfg, "TOPIC", "") or ""),
        "timeframe": str(getattr(cfg, "TIMEFRAME", "") or ""),
        "industries": [str(x) for x in (cp.get("industries") or [])],
        "output_language": str(getattr(cfg, "OUTPUT_LANGUAGE", "") or ""),
        # D Phase2 generation prompt consumes writing style + target industries.
        "writing_style": str(getattr(cfg, "WRITING_STYLE", "") or ""),
    }
    payload = json.dumps(
        {"pairs": compact_pairs, "context": context},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _save_d_phase2_checkpoint(
    checkpoint_path: Path,
    completed: dict[int, dict],
    total_pairs: int,
    pairs_signature: str,
):
    save_json(
        {
            "meta": {
                "total_pairs": total_pairs,
                "pairs_signature": pairs_signature,
            },
            "results": {str(k): v for k, v in completed.items()},
        },
        checkpoint_path,
    )


def _scenario_title(s: dict) -> str:
    return (
        s.get("title")
        or s.get("title_ja")
        or s.get("opportunity_title")
        or s.get("opportunity_title_ja")
        or ""
    )


def _normalize_selected_refs(raw_refs, valid_map: dict[str, dict]) -> list[dict]:
    """Keep only references that exist in the current source maps, with clean titles."""
    refs: list[dict] = []
    seen: set[str] = set()

    if isinstance(raw_refs, dict):
        raw_refs = [raw_refs]
    if not isinstance(raw_refs, list):
        raw_refs = []

    for ref in raw_refs:
        if not isinstance(ref, dict):
            continue
        rid = str(ref.get("id", "")).strip()
        if not rid or rid in seen or rid not in valid_map:
            continue
        refs.append({"id": rid, "title": _scenario_title(valid_map[rid])})
        seen.add(rid)

    return refs




# ── Phase 1: Select best A×C pairs ───────────────────
def phase1_select_pairs(
    expected: list[dict] = None,
    unexpected: list[dict] = None,
) -> list[dict]:
    """Smart pair selection: give LLM all A and C, pick best collision pairs."""
    if expected is None:
        expected = read_json(cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json")
    if unexpected is None:
        unexpected = read_json(cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json")

    llm = get_openai_client()
    llm.set_step("D-select-pairs")
    prompt_tpl = load_prompt("d_phase1_select_pairs.txt")

    num_pairs = _d_pool_n()
    num_a, num_c = len(expected), len(unexpected)
    # Diversity caps — generous enough that LLM won't refuse
    max_per_a = max(5, (num_pairs * 3) // num_a + 1) if num_a else 5
    max_per_c = max(5, (num_pairs * 3) // num_c + 1) if num_c else 5
    min_unique_c = num_c

    # Use sequential IDs (A-1..A-N, C-1..C-N) to avoid confusing LLM with gaps
    a_id_map = {}  # sequential → original
    for i, a in enumerate(expected, 1):
        a_id_map[f"A-{i}"] = a.get("scenario_id")
    c_id_map = {}
    for i, c in enumerate(unexpected, 1):
        c_id_map[f"C-{i}"] = c.get("scenario_id")

    expected_brief = json.dumps(
        [{"id": f"A-{i}", "title_ja": a.get("title", a.get("title_ja", ""))}
         for i, a in enumerate(expected, 1)],
        ensure_ascii=False, indent=1
    )
    unexpected_brief = json.dumps(
        [{"id": f"C-{i}", "title_ja": c.get("title", c.get("title_ja", ""))}
         for i, c in enumerate(unexpected, 1)],
        ensure_ascii=False, indent=1
    )

    target_industries = ", ".join(cfg.CLIENT_PROFILE.get("industries", cfg.CLIENT_PROFILE.get("industries_ja", [])))
    prompt = (prompt_tpl
              .replace("{expected_list}", expected_brief)
              .replace("{unexpected_list}", unexpected_brief)
              .replace("{num_pairs}", str(num_pairs))
              .replace("{max_per_a}", str(max_per_a))
              .replace("{max_per_c}", str(max_per_c))
              .replace("{min_unique_c}", str(min_unique_c))
              .replace("{target_industries}", target_industries)
              .replace("{output_language}", cfg.OUTPUT_LANGUAGE))

    # Try up to 2 times — LLM sometimes returns error analysis instead of pairs.
    # Keep `original_prompt` immutable so each retry uses a deterministic input.
    original_prompt = prompt
    retry_preamble = (
        "IGNORE ALL PREVIOUS CONSTRAINT ANALYSIS. This is NOT a math problem.\n"
        "You MUST output a JSON object with a \"pairs\" key containing an array.\n"
        "Do NOT output any error messages, feasibility analysis, or explanations.\n"
        "If constraints seem tight, just do your best — approximate solutions are fine.\n"
        "Coverage is a SOFT GOAL, not a hard requirement.\n\n"
    )
    pairs = None
    for attempt in range(1, 3):
        attempt_prompt = original_prompt if attempt == 1 else retry_preamble + original_prompt
        result = llm.call_json(attempt_prompt, model=cfg.RANK_MODEL, max_tokens=16384)

        # OpenAI response_format=json_object always returns dict; unwrap to list
        if isinstance(result, dict):
            # Check for "pairs" key first
            if "pairs" in result and isinstance(result["pairs"], list):
                pairs = result["pairs"]
                break
            # Check if LLM returned error/analysis instead of pairs
            if "error" in result or not any(isinstance(v, list) for v in result.values()):
                logger.warning(
                    f"Phase 1 attempt {attempt}: LLM returned error/analysis instead of pairs. "
                    f"Keys: {list(result.keys())}. Retrying with forceful prompt..."
                )
                continue
            pairs = next((v for v in result.values() if isinstance(v, list)), [])
            if pairs:
                break
        elif isinstance(result, list):
            pairs = result
            break

    if not pairs or not isinstance(pairs, list):
        logger.error("Phase 1 pair selection failed after retries — empty result")
        return []

    # Map sequential IDs back to original IDs
    for p in pairs:
        p["expected_ids"] = [a_id_map.get(aid, aid) for aid in p.get("expected_ids", [])]
        p["unexpected_ids"] = [c_id_map.get(cid, cid) for cid in p.get("unexpected_ids", [])]

    # Validate: each pair must have >= 1 A and >= 2 C
    valid_pairs = []
    for p in pairs:
        a_ids = p.get("expected_ids", [])
        c_ids = p.get("unexpected_ids", [])
        if len(a_ids) < 1 or len(c_ids) < 2:
            logger.warning(
                f"  Pair {p.get('pair_id')}: {len(a_ids)}A + {len(c_ids)}C — "
                f"below minimum 1A+2C, skipping"
            )
        else:
            valid_pairs.append(p)
    if len(valid_pairs) < len(pairs):
        logger.warning(
            f"Phase 1: {len(pairs) - len(valid_pairs)} pairs rejected "
            f"(< 2A or < 2C), {len(valid_pairs)} valid"
        )
    pairs = valid_pairs

    # ── Constraint validation: check max_per_a / max_per_c ──
    a_usage: dict[str, int] = {}
    c_usage: dict[str, int] = {}
    for p in pairs:
        for aid in p.get("expected_ids", []):
            a_usage[aid] = a_usage.get(aid, 0) + 1
        for cid in p.get("unexpected_ids", []):
            c_usage[cid] = c_usage.get(cid, 0) + 1
    overused_a = {aid: cnt for aid, cnt in a_usage.items() if cnt > max_per_a}
    overused_c = {cid: cnt for cid, cnt in c_usage.items() if cnt > max_per_c}
    if overused_a:
        logger.warning(f"⚠ CONSTRAINT: {len(overused_a)} A scenarios exceed max_per_a={max_per_a}: {dict(list(overused_a.items())[:10])}")
    if overused_c:
        logger.warning(f"⚠ CONSTRAINT: {len(overused_c)} C scenarios exceed max_per_c={max_per_c}: {dict(list(overused_c.items())[:10])}")

    # ── Coverage validation ──
    all_a_ids = {a.get("scenario_id") for a in expected}
    all_c_ids = {c.get("scenario_id") for c in unexpected}
    used_a_ids = set()
    used_c_ids = set()
    for p in pairs:
        used_a_ids.update(p.get("expected_ids", []))
        used_c_ids.update(p.get("unexpected_ids", []))

    # A coverage: hard requirement (all must appear)
    missing_a = all_a_ids - used_a_ids
    if missing_a:
        logger.warning(
            f"⚠ A COVERAGE GAP: {len(missing_a)} Expected Scenarios not in any pair: "
            f"{sorted(missing_a)}. Prompt requires full A coverage — "
            f"consider re-running or manually adding pairs."
        )
    else:
        logger.info(f"  A coverage check passed: all {len(all_a_ids)} A scenarios used")

    # C coverage: hard requirement (all must appear)
    missing_c = all_c_ids - used_c_ids
    c_coverage_pct = len(used_c_ids) / len(all_c_ids) * 100 if all_c_ids else 0
    if missing_c:
        logger.warning(
            f"⚠ C COVERAGE GAP: {len(missing_c)} Unexpected Scenarios not in any pair "
            f"({len(used_c_ids)}/{len(all_c_ids)} = {c_coverage_pct:.0f}%). "
            f"Missing: {sorted(missing_c)[:20]}{'...' if len(missing_c) > 20 else ''}"
        )
    else:
        logger.info(f"  C coverage check passed: all {len(all_c_ids)} C scenarios used")

    for p in pairs:
        p.setdefault("generation_mode", "select_pairs")
        p.setdefault("generation_n", num_pairs)
    save_json(pairs, cfg.INTERMEDIATE_DIR / "d_phase1_pairs.json")
    logger.info(f"Phase 1 done: {len(pairs)} pairs selected")
    return pairs


# ── Matrix mode: generate all A×C pairs ──────────────
def phase1_random_pairs(
    expected: list[dict] = None,
    unexpected: list[dict] = None,
) -> list[dict]:
    """Random pairing: randomly combine A and C scenarios into D_GENERATE_N pairs."""
    import random

    if expected is None:
        expected = read_json(cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json")
    if unexpected is None:
        unexpected = read_json(cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json")

    if not expected or not unexpected:
        raise ValueError(
            f"Cannot pair: need both Expected (got {len(expected)}) and Unexpected (got {len(unexpected)}). "
            "Re-run A1 and C first."
        )

    num_pairs = _d_pool_n()
    pairs = []
    # Fixed shape: 1 A x 2 C per pair. Prior 1-3 x 1-3 randomness
    # produced 6-source pairs that forced the LLM to pad with tangentially
    # related C scenarios. Min 1A+2C keeps collisions clean.
    n_a = 1
    n_c = 2 if len(unexpected) >= 2 else 1
    for i in range(num_pairs):
        sampled_a = random.sample(expected, min(n_a, len(expected)))
        sampled_c = random.sample(unexpected, min(n_c, len(unexpected)))
        pairs.append({
            "pair_id": i + 1,
            "expected_ids": [a.get("scenario_id") for a in sampled_a],
            "unexpected_ids": [c.get("scenario_id") for c in sampled_c],
            "collision_hypothesis_ja": "",
            "generation_mode": "random",
            "generation_n": num_pairs,
        })

    logger.info(f"Random mode: {num_pairs} random pairs from {len(expected)}A × {len(unexpected)}C")
    save_json(pairs, cfg.INTERMEDIATE_DIR / "d_phase1_pairs.json")
    return pairs


def matrix_all_pairs(
    expected: list[dict] = None,
    unexpected: list[dict] = None,
) -> list[dict]:
    """Generate all A×C pairs for matrix mode (forced collision)."""
    if expected is None:
        expected = read_json(cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json")
    if unexpected is None:
        unexpected = read_json(cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json")

    pairs = []
    for i, (a, c) in enumerate(product(expected, unexpected)):
        pairs.append({
            "pair_id": i + 1,
            "expected_ids": [a.get("scenario_id")],
            "unexpected_ids": [c.get("scenario_id")],
            "collision_hypothesis_ja": "",  # no pre-hypothesis in matrix mode
            "generation_mode": "matrix",
            "generation_n": len(expected) * len(unexpected),
        })

    logger.info(f"Matrix mode: {len(pairs)} pairs ({len(expected)}A × {len(unexpected)}C)")
    save_json(pairs, cfg.INTERMEDIATE_DIR / "d_phase1_pairs.json")
    return pairs


def _is_pairs_checkpoint_fresh(
    pairs_path: Path,
    pairs: list[dict],
    expected: list[dict],
    unexpected: list[dict],
    mode: str,
) -> bool:
    """Return True only when cached pairs are compatible with current A/C inputs."""
    if not isinstance(pairs, list) or not pairs:
        return False

    expected_ids = {str(a.get("scenario_id", "")) for a in expected if a.get("scenario_id")}
    unexpected_ids = {str(c.get("scenario_id", "")) for c in unexpected if c.get("scenario_id")}

    used_a_ids: set[str] = set()
    used_c_ids: set[str] = set()

    for p in pairs:
        if not isinstance(p, dict):
            return False
        for aid in p.get("expected_ids", []):
            if aid:
                used_a_ids.add(str(aid))
        for cid in p.get("unexpected_ids", []):
            if cid:
                used_c_ids.add(str(cid))

    if not used_a_ids or not used_c_ids:
        return False
    if not used_a_ids.issubset(expected_ids):
        return False
    if not used_c_ids.issubset(unexpected_ids):
        return False

    # Matrix mode must match exact A×C pair count.
    if mode == "matrix" and len(pairs) != len(expected) * len(unexpected):
        return False

    # Mode mismatch: cached pairs produced by a different mode are not reusable.
    pair_modes = {str(p.get("generation_mode", "")) for p in pairs}
    if pair_modes and pair_modes != {mode}:
        return False

    # Pair count mismatch (random / select_pairs): cached N != current pool_n.
    if mode in ("random", "select_pairs"):
        expected_pool_n = _d_pool_n()
        if len(pairs) != expected_pool_n:
            return False

    # Cached pairs must be newer than source A/C files.
    try:
        a_path = cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json"
        c_path = cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json"
        source_mtime = max(a_path.stat().st_mtime, c_path.stat().st_mtime)
        if pairs_path.stat().st_mtime < source_mtime:
            return False
    except OSError:
        return False

    return True


# ── Phase 2: Generate full scenarios ─────────────────
def phase2_generate(
    pairs: list[dict] = None,
    expected: list[dict] = None,
    unexpected: list[dict] = None,
) -> list[dict]:
    """Generate Opportunity Scenarios for each selected pair."""
    if pairs is None:
        pairs = read_json(cfg.INTERMEDIATE_DIR / "d_phase1_pairs.json")
    if expected is None:
        expected = read_json(cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json")
    if unexpected is None:
        unexpected = read_json(cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json")

    if not expected:
        raise RuntimeError(
            "Step D requires A1 output but A1_expected_scenarios_ja.json is missing or empty — run Step A1 first."
        )
    if not unexpected:
        raise RuntimeError(
            "Step D requires C output but C_unexpected_scenarios_ja.json is missing or empty — run Step C first."
        )
    if not pairs:
        raise RuntimeError(
            "Step D has no pairs to process — Phase 1 produced an empty list. Re-run D Phase 1 or check logs."
        )

    # Build lookup maps
    a_map = {a.get("scenario_id"): a for a in expected}
    c_map = {c.get("scenario_id"): c for c in unexpected}

    llm = get_client()
    llm.set_step("D-generate")
    prompt_tpl = load_prompt("d_phase2_generate.txt")

    # Brief lists for multi-selection reference
    all_expected_brief = json.dumps(
        [{"id": a.get("scenario_id"), "title_ja": a.get("title", a.get("title_ja", ""))}
         for a in expected],
        ensure_ascii=False, indent=1
    )
    all_unexpected_brief = json.dumps(
        [{"id": c.get("scenario_id"), "title_ja": c.get("title", c.get("title_ja", ""))}
         for c in unexpected],
        ensure_ascii=False, indent=1
    )

    total_pairs = len(pairs)
    pairs_signature = _d_phase2_signature(pairs)
    indexed_pairs = [(i, pair) for i, pair in enumerate(pairs)]

    # ── Checkpoint ──────────────────────────────────
    checkpoint_path = cfg.INTERMEDIATE_DIR / "d_phase2_checkpoint.json"
    completed: dict[int, dict] = {}
    if checkpoint_path.exists():
        try:
            ckpt = read_json(checkpoint_path)
            meta = ckpt.get("meta", {}) if isinstance(ckpt, dict) else {}
            saved_sig = meta.get("pairs_signature")
            saved_total = meta.get("total_pairs")
            if saved_sig != pairs_signature or saved_total != total_pairs:
                logger.info(
                    "  D-Phase2 checkpoint is stale (pairs changed) - starting fresh"
                )
            else:
                saved_results = ckpt.get("results") or ckpt.get("batch_results") or {}
                completed = {int(k): v for k, v in saved_results.items()}
                logger.info(f"  D-Phase2 checkpoint: {len(completed)}/{total_pairs} done")
        except Exception:
            logger.warning("  D-Phase2 checkpoint load failed — starting fresh")

    remaining = [(i, pair) for i, pair in indexed_pairs if i not in completed]
    logger.info(f"Phase 2: {total_pairs} pairs, {len(remaining)} remaining")

    ckpt_lock = threading.Lock()

    def make_prompt(item):
        idx, pair = item
        # Gather A and C scenario data for this pair
        a_ids = pair.get("expected_ids", [])
        c_ids = pair.get("unexpected_ids", [])
        missing_a = [aid for aid in a_ids if aid not in a_map]
        missing_c = [cid for cid in c_ids if cid not in c_map]
        if missing_a:
            logger.warning(f"  Pair {idx}: missing A scenario data for IDs {missing_a}")
        if missing_c:
            logger.warning(f"  Pair {idx}: missing C scenario data for IDs {missing_c}")
        a_data = [strip_zh(a_map[aid]) for aid in a_ids if aid in a_map]
        c_data = [strip_zh(c_map[cid]) for cid in c_ids if cid in c_map]
        if not a_data or not c_data:
            logger.error(f"  Pair {idx}: EMPTY context (a_data={len(a_data)}, c_data={len(c_data)}) — output quality will be degraded")

        industries = cfg.CLIENT_PROFILE.get("industries", cfg.CLIENT_PROFILE.get("industries_ja", []))
        return (prompt_tpl
                .replace("{writing_style}", cfg.WRITING_STYLE)
                .replace("{expected}", json.dumps(a_data, ensure_ascii=False, indent=1))
                .replace("{unexpected}", json.dumps(c_data, ensure_ascii=False, indent=1))
                .replace("{all_expected_brief}", all_expected_brief)
                .replace("{all_unexpected_brief}", all_unexpected_brief)
                .replace("{collision_hypothesis}",
                         pair.get("collision_hypothesis_ja", "")
                         or "（No pre-hypothesis — analyze the A×C pair and identify the collision yourself.）")
                .replace("{target_industries_ja}",
                         ", ".join(f"[{x}]" for x in industries))
                .replace("{output_language}", cfg.OUTPUT_LANGUAGE)
                .replace("{index}", str(pair.get("pair_id", idx + 1))))

    def on_done(flat_idx, result):
        abs_idx = remaining[flat_idx][0]
        with ckpt_lock:
            if result and isinstance(result, dict):
                completed[abs_idx] = result
            if len(completed) % 10 == 0 or len(completed) == total_pairs:
                _save_d_phase2_checkpoint(
                    checkpoint_path,
                    completed,
                    total_pairs,
                    pairs_signature,
                )

    if remaining:
        llm.concurrent_batch_call(
            items=remaining,
            prompt_fn=make_prompt,
            model=cfg.MODEL_HEAVY,
            desc="D-Phase2 Generate",
            max_workers=cfg.MAX_CONCURRENT,
            on_item_done=on_done,
            temperature=0.75,  # Higher temp for creative opportunity generation
        )
        _save_d_phase2_checkpoint(
            checkpoint_path,
            completed,
            total_pairs,
            pairs_signature,
        )
    else:
        logger.info("  All D-Phase2 pairs complete — assembling from checkpoint")

    pair_map = {i: pairs[i] for i in range(total_pairs)}
    all_scenarios = []
    for i in range(total_pairs):
        if i not in completed:
            continue
        item = completed[i]
        if not isinstance(item, dict):
            continue
        s = dict(item)
        pair = pair_map.get(i, {})
        s["_pair_expected_ids"] = [str(aid) for aid in pair.get("expected_ids", [])]
        s["_pair_unexpected_ids"] = [str(cid) for cid in pair.get("unexpected_ids", [])]
        all_scenarios.append(s)

    failed_pairs = [i for i in range(total_pairs) if i not in completed]
    if failed_pairs:
        logger.warning(
            f"⚠ D-Phase2: {len(failed_pairs)}/{total_pairs} pairs failed to generate scenarios: "
            f"{failed_pairs[:10]}{'...' if len(failed_pairs) > 10 else ''}"
        )

    # Normalize selected references to current A/C outputs.
    min_c_needed = 2 if len(c_map) >= 2 else (1 if c_map else 0)
    for s in all_scenarios:
        selected_a = _normalize_selected_refs(s.get("selected_expected"), a_map)
        selected_c = _normalize_selected_refs(s.get("selected_unexpected"), c_map)

        pair_a_ids = [aid for aid in s.pop("_pair_expected_ids", []) if aid in a_map]
        pair_c_ids = [cid for cid in s.pop("_pair_unexpected_ids", []) if cid in c_map]

        if not selected_a:
            for aid in pair_a_ids:
                selected_a.append({"id": aid, "title": _scenario_title(a_map[aid])})
                break

        if min_c_needed > 0 and len(selected_c) < min_c_needed:
            seen_c = {x.get("id") for x in selected_c}
            for cid in pair_c_ids:
                if cid in seen_c:
                    continue
                selected_c.append({"id": cid, "title": _scenario_title(c_map[cid])})
                seen_c.add(cid)
                if len(selected_c) >= min_c_needed:
                    break

        s["selected_expected"] = selected_a
        s["selected_unexpected"] = selected_c

    # Enforce stable sequential IDs for downstream ranking/traceability
    for idx, s in enumerate(all_scenarios, 1):
        s["scenario_id"] = f"D-{idx}"

    save_json(all_scenarios, cfg.INTERMEDIATE_DIR / "d_phase2_scenarios.json")
    logger.info(f"Phase 2 done: {len(all_scenarios)}/{total_pairs} scenarios generated")
    return all_scenarios


# ── Export C scenarios used in D ──────────────────────
def _export_c_used_in_d(d_final: list[dict]):
    """Export only the C scenarios referenced by final D scenarios.
    Writes to C_used_in_D* files so original full C outputs remain untouched."""
    # Collect all C IDs used in D
    used_c_ids = set()
    for d in d_final:
        for c_ref in d.get("selected_unexpected", []):
            cid = c_ref.get("id", "")
            if cid:
                used_c_ids.add(cid)

    if not used_c_ids:
        logger.warning("No C scenario IDs found in D scenarios — skipping C re-export")
        return

    # Load already-translated C output (ja has all fields; zh merged if available)
    ja_path = cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json"
    zh_path = cfg.OUTPUT_DIR / "C_unexpected_scenarios_zh.json"

    if not ja_path.exists():
        # Fall back to intermediate (untranslated)
        ja_path = cfg.INTERMEDIATE_DIR / "c_phase2_scenarios.json"
    if not ja_path.exists():
        logger.warning("Cannot find C scenarios file — skipping C re-export")
        return

    all_c_ja = read_json(ja_path)
    c_map = {c.get("scenario_id"): c for c in all_c_ja}

    # Load B zh signal titles for source_signals translation
    b_zh_title_map = {}
    b_zh_path = cfg.OUTPUT_DIR / "B_selected_weak_signals_zh.json"
    if b_zh_path.exists():
        try:
            b_zh = read_json(b_zh_path)
            b_zh_title_map = {str(s.get("signal_id", "")): s.get("title", "") for s in b_zh}
        except Exception:
            logger.warning("Failed to load B zh titles — source_signals will not have zh titles")

    # Merge zh fields if available
    if zh_path.exists():
        try:
            all_c_zh = read_json(zh_path)
            zh_map = {c.get("scenario_id"): c for c in all_c_zh}

            # zh source may be either:
            # 1) bilingual objects with *_zh fields, or
            # 2) split zh file with clean keys (title/overview/...) already in Chinese.
            text_field_candidates = {
                "title", "overview", "why", "who", "where", "what_how",
                "timeline_description", "ranking_note", "theme", "synthesis_hint",
            }

            def _has_value(v):
                return v not in (None, "", [], {})

            for sid, c in c_map.items():
                zh = zh_map.get(sid, {})
                if not isinstance(zh, dict):
                    continue

                # Case 1: already bilingual with *_zh keys
                zh_suffixed = {k: v for k, v in zh.items() if k.endswith("_zh") and _has_value(v)}
                if zh_suffixed:
                    c.update(zh_suffixed)
                    continue

                # Case 2: split zh file with clean keys (no *_zh suffix)
                ja_keys = [k for k in c.keys() if k.endswith("_ja")]
                if ja_keys:
                    # If current record has *_ja keys, map base key -> *_zh
                    for ja_key in ja_keys:
                        base = ja_key[:-3]
                        v = zh.get(base)
                        if _has_value(v):
                            c[f"{base}_zh"] = v
                else:
                    # If current record uses clean Japanese keys, use known text fields
                    for base in text_field_candidates:
                        v = zh.get(base)
                        if _has_value(v):
                            c[f"{base}_zh"] = v

                # Merge nested source_signals titles from B zh output
                # (B already has Chinese translations; C zh may still have Japanese)
                for sig in c.get("source_signals", []):
                    signal_id = str(sig.get("signal_id", ""))
                    zh_title = b_zh_title_map.get(signal_id, "")
                    if zh_title:
                        if "title" in sig and "title_ja" not in sig:
                            sig["title_ja"] = sig.pop("title")
                        sig["title_zh"] = zh_title
        except Exception as e:
            logger.warning(f"Failed to merge C zh data: {e}")

    # Filter to only used C scenarios
    used_c = [c_map[cid] for cid in sorted(used_c_ids) if cid in c_map]

    if not used_c:
        logger.warning(f"None of the {len(used_c_ids)} referenced C IDs found in C data — skipping C re-export")
        return

    save_split(used_c, cfg.OUTPUT_DIR, "C_used_in_D")

    # Excel export for C
    df = pd.DataFrame([
        {
            "scenario_id": s.get("scenario_id"),
            "total_score": s.get("total_score", 0),
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
                f"{sig.get('signal_id', '')}: {sig.get('title_ja', sig.get('title', ''))}"
                for sig in s.get("source_signals", [])
            ),
            "source_signals_zh": "\n".join(
                f"{sig.get('signal_id', '')}: {sig.get('title_zh', '')}"
                for sig in s.get("source_signals", [])
            ),
            "ranking_note_ja": s.get("ranking_note_ja", ""),
            "ranking_note_zh": s.get("ranking_note_zh", ""),
        }
        for s in used_c
    ])
    save_excel(df, cfg.OUTPUT_DIR / "C_used_in_D.xlsx")

    logger.info(f"C re-export: {len(used_c)} C scenarios used in top {len(d_final)} D scenarios")


# ── Phase 3: Rank & Select ───────────────────────────
def phase3_rank(scenarios: list[dict] = None) -> list[dict]:
    """Rank scenarios, keep all gate-passing items, then add global review flags."""
    if scenarios is None:
        scenarios = read_json(cfg.INTERMEDIATE_DIR / "d_phase2_scenarios.json")

    llm = get_openai_client()
    llm.set_step("D-rank")

    D_DIMS = ["unexpected_score", "impact_score", "plausibility_score"]  # all 3 weighted

    d_summary_fn = lambda s: {
        "scenario_id": s.get("scenario_id"),
        "opportunity_title_ja": s.get("opportunity_title_ja", ""),
        "collision_insight_ja": s.get("collision_insight_ja", ""),
        "selected_expected": s.get("selected_expected", []),
        "selected_unexpected": s.get("selected_unexpected", []),
    }

    scenarios, final = rank_and_select(
        scenarios, D_DIMS,
        load_prompt("d_phase3_rank.txt"),
        llm, cfg.RANK_MODEL,
        summary_fn=d_summary_fn,
        prompt_vars={
            "topic": cfg.TOPIC,
            "target_industries": ", ".join(cfg.CLIENT_PROFILE.get("industries", cfg.CLIENT_PROFILE.get("industries_ja", []))),
            "output_language": cfg.OUTPUT_LANGUAGE,
        },
        step_label="D-Phase3",
        weights=cfg.D_WEIGHTS,
    )

    # total_score = sum of all 3 dims (matches LLM-returned total). Matrix axes
    # remain Unexpectedness × Impact only — plausibility contributes to ranking
    # but not to the visual quadrant placement.
    for s in scenarios:
        u = s.get("unexpected_score", 0) or 0
        i = s.get("impact_score", 0) or 0
        p = s.get("plausibility_score", 0) or 0
        s["total_score"] = u + i + p

    final = pick_final(
        final, k=cfg.D_GENERATE_N, llm=llm, model=cfg.RANK_MODEL,
        fields=["opportunity_title_ja", "collision_insight_ja", "background_ja", "implications_for_company_ja"],
        topic=cfg.TOPIC, step_label="D-Phase3",
    )

    for s in final:
        u = s.get("unexpected_score", 0) or 0
        i = s.get("impact_score", 0) or 0
        p = s.get("plausibility_score", 0) or 0
        s["total_score"] = u + i + p

    final.sort(key=lambda s: (
        -(s.get("total_score", 0) or 0),
        -(s.get("impact_score", 0) or 0),
        -(s.get("plausibility_score", 0) or 0),
        str(s.get("scenario_id", "")),
    ))

    # Translate and save
    if getattr(cfg, "TRANSLATE_ENABLED", False):
        oai = get_openai_client()
        oai.set_step("D-translate")
        final = translate_to_zh(final, oai, cfg.TRANSLATE_MODEL)
    save_split(final, cfg.OUTPUT_DIR, "D_opportunity_scenarios")

    # Re-export only the C scenarios used in final D scenarios
    _export_c_used_in_d(final)

    # Excel export
    df = pd.DataFrame([
        {
            "scenario_id": s.get("scenario_id"),
            "total_score": s.get("total_score", 0),
            "weighted_score": s.get("weighted_score", 0),
            "unexpected_score": s.get("unexpected_score", 0),
            "impact_score": s.get("impact_score", 0),
            "plausibility_score": s.get("plausibility_score", 0),
            "opportunity_title_ja": s.get("opportunity_title_ja", ""),
            "opportunity_title_zh": s.get("opportunity_title_zh", ""),
            "selected_expected": "\n".join(
                f"{e.get('id','')}: {e.get('title','')}"
                for e in (s.get("selected_expected") if isinstance(s.get("selected_expected"), list)
                          else [s.get("selected_expected", {})])
                if e
            ),
            "selected_unexpected": "\n".join(
                f"{e.get('id','')}: {e.get('title','')}"
                for e in (s.get("selected_unexpected") if isinstance(s.get("selected_unexpected"), list)
                          else [s.get("selected_unexpected", {})])
                if e
            ),
            "collision_insight_ja": s.get("collision_insight_ja", ""),
            "collision_insight_zh": s.get("collision_insight_zh", ""),
            "background_ja": s.get("background_ja", ""),
            "background_zh": s.get("background_zh", ""),
            "about_the_future_ja": s.get("about_the_future_ja", ""),
            "about_the_future_zh": s.get("about_the_future_zh", ""),
            "implications_ja": "\n".join(
                s.get("implications_for_company_ja", [])
            ),
            "implications_zh": "\n".join(
                s.get("implications_for_company_zh", [])
            ),
            "company_approach_ja": "\n".join(s.get("company_approach_ja", [])),
            "company_approach_zh": "\n".join(s.get("company_approach_zh", [])),
            "transformation_points_ja": "\n".join(s.get("transformation_points_ja", [])),
            "transformation_points_zh": "\n".join(s.get("transformation_points_zh", [])),
            "ranking_note_ja": s.get("ranking_note_ja", ""),
        }
        for s in final
    ])
    save_excel(df, cfg.OUTPUT_DIR / "D_opportunity_scenarios.xlsx")

    # Matrix classification: Unexpectedness × Impact
    # Thresholds are the MEDIANS of the selected set — matches JRI's "map of the
    # creative landscape" intent (relative positioning), not a fixed absolute cutoff.
    # Guard: need at least 3 scenarios for meaningful median-based quadrant split.
    if getattr(cfg, "D_MATRIX_MODE", False) and len(final) >= 3:
        import statistics
        u_vals = [s.get("unexpected_score", 0) or 0 for s in final]
        i_vals = [s.get("impact_score", 0) or 0 for s in final]
        u_mid = statistics.median(u_vals)
        i_mid = statistics.median(i_vals)
        for s in final:
            u = s.get("unexpected_score", 0) or 0
            i = s.get("impact_score", 0) or 0
            if u >= u_mid and i >= i_mid:
                s["matrix_quadrant"] = "breakthrough"
            elif u >= u_mid and i < i_mid:
                s["matrix_quadrant"] = "surprising"
            elif u < u_mid and i >= i_mid:
                s["matrix_quadrant"] = "incremental"
            else:
                s["matrix_quadrant"] = "low_priority"
        # Re-save with matrix labels
        save_split(final, cfg.OUTPUT_DIR, "D_opportunity_scenarios")
        logger.info(f"Matrix classification applied: "
                    f"{sum(1 for s in final if s.get('matrix_quadrant')=='breakthrough')} breakthrough, "
                    f"{sum(1 for s in final if s.get('matrix_quadrant')=='surprising')} surprising, "
                    f"{sum(1 for s in final if s.get('matrix_quadrant')=='incremental')} incremental, "
                    f"{sum(1 for s in final if s.get('matrix_quadrant')=='low_priority')} low_priority")
    elif getattr(cfg, "D_MATRIX_MODE", False):
        logger.info(f"Matrix classification skipped: need ≥3 scenarios, got {len(final)}")

    logger.info(f"Phase 3 done: {len(final)} scenarios written to output after gate filter and review")
    return final



# ── Run All ─────────────────────────────────────────
def run() -> list[dict]:
    logger.info("=" * 60)
    logger.info(f"Step D: Opportunity Scenario Synthesis (mode={cfg.D_MODE})")
    logger.info("=" * 60)

    expected = read_json(cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json")
    unexpected = read_json(cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json")

    pairs_path = cfg.INTERMEDIATE_DIR / "d_phase1_pairs.json"
    if pairs_path.exists():
        try:
            pairs = read_json(pairs_path)
        except Exception as e:
            logger.warning(f"Failed to read existing Phase 1 pairs ({pairs_path.name}): {e} — re-running Phase 1")
            pairs = None
        else:
            if _is_pairs_checkpoint_fresh(pairs_path, pairs, expected, unexpected, cfg.D_MODE):
                logger.info(f"Reusing existing Phase 1 pairs: {len(pairs)} pairs from {pairs_path.name}")
            else:
                logger.info("Existing Phase 1 pairs are stale/incompatible with current A/C outputs — re-running Phase 1")
                pairs = None
    else:
        pairs = None

    if pairs is None:
        if cfg.D_MODE == "random":
            pairs = phase1_random_pairs(expected, unexpected)
        elif cfg.D_MODE == "matrix":
            pairs = matrix_all_pairs(expected, unexpected)
        else:
            pairs = phase1_select_pairs(expected, unexpected)

    scenarios = phase2_generate(pairs, expected, unexpected)
    final = phase3_rank(scenarios)

    logger.info(f"Step D complete: {len(final)} Opportunity Scenarios")
    return final


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
