"""
Re-run ranking, gate filtering, and global review for a specific step (A, C, or D).
Uses existing generated scenarios and re-runs only the post-generation phase.

Usage:
    python3 rerank.py A                  # Re-rank A, output all passed scenarios
    python3 rerank.py C --limit 100      # Re-rank C, keep first 100 after review
    python3 rerank.py D --no-translate   # Re-rank D, refresh JA output only

    # Backward-compatible alias:
    python3 rerank.py A --deliver 30
"""
import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

import config as cfg
from utils.data_io import (
    enforce_gate, load_prompt, llm_review, rank_and_select, read_json, save_excel, save_json,
)
from utils.bilingual import save_split, split_bilingual, translate_to_zh

OUTPUT_DIR = cfg.OUTPUT_DIR
INTERMEDIATE_DIR = cfg.INTERMEDIATE_DIR
BACKUP_DIR = OUTPUT_DIR / "backup"


def backup_file(path: Path):
    if not path.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"{path.stem}_{ts}{path.suffix}"
    shutil.copy2(path, dest)
    logger.info(f"Backup: {dest}")


def _backup_outputs(base_name: str):
    for suffix in ["_ja", "_zh"]:
        backup_file(OUTPUT_DIR / f"{base_name}{suffix}.json")
    backup_file(OUTPUT_DIR / f"{base_name}.xlsx")


def _save_json_outputs(data: list[dict], base_name: str, *, translate: bool):
    if translate:
        save_split(data, OUTPUT_DIR, base_name)
        return

    ja_path = OUTPUT_DIR / f"{base_name}_ja.json"
    with open(ja_path, "w", encoding="utf-8") as f:
        json.dump(split_bilingual(data, "ja"), f, ensure_ascii=False, indent=2)
    logger.info(f"Saved: {ja_path}")
    logger.info(f"Skipped zh translation for {base_name}; existing zh output was not updated")


def _apply_limit(scenarios: list[dict], limit: int | None, *, step_label: str) -> list[dict]:
    if limit is None:
        return scenarios
    limited = scenarios[:limit]
    logger.info(
        f"{step_label}: applied manual limit={limit}, keeping {len(limited)} of {len(scenarios)} passed scenarios"
    )
    return limited


def _a1_summary(s: dict) -> dict:
    return {
        "scenario_id": s.get("scenario_id"),
        "title_ja": s.get("title_ja", ""),
        "change_from_ja": (s.get("change_from_ja") or "")[:300],
        "change_to_ja": (s.get("change_to_ja") or "")[:300],
    }


def _c_summary(s: dict) -> dict:
    return {
        "scenario_id": s.get("scenario_id"),
        "title_ja": s.get("title_ja", ""),
        "overview_ja": (s.get("overview_ja") or "")[:500],
        "source_signals": [
            sig.get("title_ja", "") for sig in s.get("source_signals", [])
        ],
    }


def _d_summary(s: dict) -> dict:
    return {
        "scenario_id": s.get("scenario_id"),
        "opportunity_title_ja": s.get("opportunity_title_ja", ""),
        "collision_insight_ja": s.get("collision_insight_ja", ""),
        "selected_expected": s.get("selected_expected", []),
        "selected_unexpected": s.get("selected_unexpected", []),
    }


def rerank_a(limit: int | None = None, translate: bool = True):
    """Re-rank A scenarios from the generated pool."""
    pool_path = INTERMEDIATE_DIR / "a1_phase3_scenarios.json"
    scenarios = read_json(pool_path)
    logger.info(f"A: Loaded {len(scenarios)} scenarios from {pool_path.name}")

    from utils.openai_client import get_openai_client
    llm = get_openai_client()
    llm.set_step("A1-rerank")

    A1_DIMS = ["structural_depth", "irreversibility", "industry_relevance", "topic_relevance"]

    scenarios, final = rank_and_select(
        scenarios, A1_DIMS,
        load_prompt("a1_phase4_rank.txt"),
        llm, cfg.RANK_MODEL,
        summary_fn=_a1_summary,
        prompt_vars={
            "topic": cfg.TOPIC,
            "target_industries": ", ".join(cfg.CLIENT_PROFILE["industries"]),
        },
        step_label="A1-Rerank",
        min_dim_scores=cfg.A1_MIN_DIM_SCORES,
    )

    # Save full ranked list
    save_json(scenarios, INTERMEDIATE_DIR / "a1_phase4_ranked.json")

    final = llm_review(
        final, llm, cfg.RANK_MODEL,
        step="A1",
        summary_fn=_a1_summary,
        prompt_vars={"topic": cfg.TOPIC},
        step_label="A1-Rerank",
    )
    final = enforce_gate(final, cfg.A1_MIN_DIM_SCORES, step_label="A1-Rerank")
    final = _apply_limit(final, limit, step_label="A1-Rerank")

    # Backup and save output
    _backup_outputs("A1_expected_scenarios")

    if translate:
        oai = get_openai_client()
        oai.set_step("A1-rerank-translate")
        final = translate_to_zh(final, oai, cfg.TRANSLATE_MODEL)

    _save_json_outputs(final, "A1_expected_scenarios", translate=translate)

    # Excel
    import pandas as pd
    df = pd.DataFrame([
        {
            "scenario_id": s.get("scenario_id"),
            "total_score": s.get("total_score"),
            "score_structural_depth": s.get("score_structural_depth", 0),
            "score_irreversibility": s.get("score_irreversibility", 0),
            "score_industry_relevance": s.get("score_industry_relevance", 0),
            "score_topic_relevance": s.get("score_topic_relevance", 0),
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
    save_excel(df, OUTPUT_DIR / "A1_expected_scenarios.xlsx")

    logger.info(f"\nA rerank done: {len(final)} scenarios written (from {len(scenarios)} scored scenarios)")
    return final


def rerank_c(limit: int | None = None, translate: bool = True):
    """Re-rank C scenarios from the generated pool."""
    pool_path = INTERMEDIATE_DIR / "c_phase2_scenarios.json"
    scenarios = read_json(pool_path)
    logger.info(f"C: Loaded {len(scenarios)} scenarios from {pool_path.name}")

    from utils.openai_client import get_openai_client
    llm = get_openai_client()
    llm.set_step("C-rerank")

    C_DIMS = ["unexpectedness", "social_impact", "uncertainty"]

    scenarios, final = rank_and_select(
        scenarios, C_DIMS,
        load_prompt("c_phase3_rank.txt"),
        llm, cfg.RANK_MODEL,
        summary_fn=_c_summary,
        prompt_vars={"topic": cfg.TOPIC},
        step_label="C-Rerank",
        min_dim_scores=cfg.C_MIN_DIM_SCORES,
    )

    final = llm_review(
        final, llm, cfg.RANK_MODEL,
        step="C",
        summary_fn=_c_summary,
        prompt_vars={"topic": cfg.TOPIC},
        step_label="C-Rerank",
    )
    final = enforce_gate(final, cfg.C_MIN_DIM_SCORES, step_label="C-Rerank")
    final = _apply_limit(final, limit, step_label="C-Rerank")

    # Backup and save
    _backup_outputs("C_unexpected_scenarios")

    if translate:
        oai = get_openai_client()
        oai.set_step("C-rerank-translate")
        final = translate_to_zh(final, oai, cfg.TRANSLATE_MODEL)

    _save_json_outputs(final, "C_unexpected_scenarios", translate=translate)

    # Excel
    import pandas as pd
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
    save_excel(df, OUTPUT_DIR / "C_unexpected_scenarios.xlsx")

    logger.info(f"\nC rerank done: {len(final)} scenarios written (from {len(scenarios)} scored scenarios)")
    return final


def rerank_d(limit: int | None = None, translate: bool = True):
    """Re-rank D scenarios from the generated pool."""
    pool_path = INTERMEDIATE_DIR / "d_phase2_scenarios.json"
    scenarios = read_json(pool_path)
    logger.info(f"D: Loaded {len(scenarios)} scenarios from {pool_path.name}")

    from utils.openai_client import get_openai_client
    llm = get_openai_client()
    llm.set_step("D-rerank")

    D_DIMS = ["collision_score", "unexpected_score", "impact_score", "plausibility_score", "topic_relevance_score"]

    scenarios, final = rank_and_select(
        scenarios, D_DIMS,
        load_prompt("d_phase3_rank.txt"),
        llm, cfg.RANK_MODEL,
        summary_fn=_d_summary,
        prompt_vars={
            "topic": cfg.TOPIC,
            "target_industries": ", ".join(cfg.CLIENT_PROFILE["industries_ja"]),
        },
        step_label="D-Rerank",
        min_dim_scores=cfg.D_MIN_DIM_SCORES,
    )

    final = llm_review(
        final, llm, cfg.RANK_MODEL,
        step="D",
        summary_fn=_d_summary,
        prompt_vars={
            "topic": cfg.TOPIC,
            "target_industries": ", ".join(cfg.CLIENT_PROFILE["industries_ja"]),
        },
        step_label="D-Rerank",
    )
    final = enforce_gate(final, cfg.D_MIN_DIM_SCORES, step_label="D-Rerank")
    final = _apply_limit(final, limit, step_label="D-Rerank")

    # Backup and save
    _backup_outputs("D_opportunity_scenarios")

    if translate:
        oai = get_openai_client()
        oai.set_step("D-rerank-translate")
        final = translate_to_zh(final, oai, cfg.TRANSLATE_MODEL)

    _save_json_outputs(final, "D_opportunity_scenarios", translate=translate)

    # Re-export C_used_in_D
    from steps.step_d import _export_c_used_in_d
    _export_c_used_in_d(final)

    # Excel
    import pandas as pd
    df = pd.DataFrame([
        {
            "scenario_id": s.get("scenario_id"),
            "total_score": s.get("total_score", 0),
            "collision_score": s.get("collision_score", 0),
            "unexpected_score": s.get("unexpected_score", 0),
            "impact_score": s.get("impact_score", 0),
            "plausibility_score": s.get("plausibility_score", 0),
            "topic_relevance_score": s.get("topic_relevance_score", 0),
            "opportunity_title_ja": s.get("opportunity_title_ja", ""),
            "collision_insight_ja": s.get("collision_insight_ja", ""),
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
        }
        for s in final
    ])
    save_excel(df, OUTPUT_DIR / "D_opportunity_scenarios.xlsx")

    logger.info(f"\nD rerank done: {len(final)} scenarios written (from {len(scenarios)} scored scenarios)")
    return final


def main():
    parser = argparse.ArgumentParser(
        description="Re-run ranking, gate filtering, and global review for A, C, or D scenarios.",
        epilog="Examples: python3 rerank.py A | python3 rerank.py C --limit 100",
    )
    parser.add_argument("step", choices=["A", "C", "D"], help="Which step to re-rank")
    parser.add_argument("--limit", type=int, help="Optional cap after gate filter and global review")
    parser.add_argument("--deliver", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--no-translate", action="store_true", help="Skip translation (faster, ja-only)")

    args = parser.parse_args()
    translate = not args.no_translate
    limit = args.limit if args.limit is not None else args.deliver

    if args.limit is not None and args.deliver is not None and args.limit != args.deliver:
        parser.error("--limit and --deliver disagree")
    if limit is not None and limit <= 0:
        parser.error("--limit must be a positive integer")
    if args.deliver is not None and args.limit is None:
        logger.warning("--deliver is deprecated; use --limit instead")

    if args.step == "A":
        final = rerank_a(limit, translate=translate)
    elif args.step == "C":
        final = rerank_c(limit, translate=translate)
    elif args.step == "D":
        final = rerank_d(limit, translate=translate)

    output_names = {
        "A": "A1_expected_scenarios",
        "C": "C_unexpected_scenarios",
        "D": "D_opportunity_scenarios",
    }
    output_name = output_names[args.step]

    print(f"\n{'='*50}")
    print(f"Done! {len(final)} {args.step} scenarios in output.")
    if limit is None:
        print("Scope: all scenarios that passed gate filter and global review ordering.")
    else:
        print(f"Scope: manual limit applied after gate filter and global review (limit={limit}).")
    print(f"Review: data/output/{output_name}.xlsx")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
