"""
JRI Living Lab+ AI Scenario Pipeline — Main Runner
===================================================
Usage:
    python3 run_pipeline.py              # Run all steps A→B→C→D
    python3 run_pipeline.py --step a1    # Run only Step A-1
    python3 run_pipeline.py --step b     # Run only Step B
    python3 run_pipeline.py --step c     # Run only Step C
    python3 run_pipeline.py --step d     # Run only Step D
    python3 run_pipeline.py --step a1 --phase 1   # Summarize articles
    python3 run_pipeline.py --step a1 --phase 2   # Cluster into themes
    python3 run_pipeline.py --step a1 --phase 3   # Generate scenarios
    python3 run_pipeline.py --step a1 --phase 4   # Rank, gate filter, and global review
"""
import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from steps import step_a1, step_b, step_c, step_d
from utils.llm_client import get_client
from utils.openai_client import get_openai_client
from utils.data_io import save_json, read_json


def save_cost_report():
    """Print and save cost report, merging Claude + OpenAI costs with any existing report."""
    client = get_client()
    client.tracker.print_summary()
    report = client.tracker.to_report()

    # Merge OpenAI usage (Step B scoring/diversity + all translations)
    openai_report = get_openai_client().cost_report()
    for step, data in openai_report.items():
        if step.startswith("_"):
            continue
        report["by_step"][step] = data

    # Merge with existing report so cumulative by_step is preserved across runs
    existing_path = cfg.OUTPUT_DIR / "cost_report.json"
    if existing_path.exists():
        try:
            existing = read_json(existing_path)
            for step, data in existing.get("by_step", {}).items():
                if step not in report["by_step"]:
                    report["by_step"][step] = data
            # Recalculate totals from merged by_step
            total_in  = sum(v["input_tokens"]  for v in report["by_step"].values())
            total_out = sum(v["output_tokens"] for v in report["by_step"].values())
            report["total"] = {
                "calls":        sum(v["calls"] for v in report["by_step"].values()),
                "input_tokens": total_in,
                "output_tokens": total_out,
                "total_tokens": total_in + total_out,
                "cost_usd":     round(sum(v["cost_usd"] for v in report["by_step"].values()), 4),
            }
        except Exception as e:
            logging.getLogger("pipeline").warning(f"Cost report merge failed (keeping current run data): {e}")

    save_json(report, existing_path)
    logging.getLogger("pipeline").info(
        f"Cost report saved: {existing_path}"
    )


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(cfg.BASE_DIR / "pipeline.log", encoding="utf-8"),
        ],
    )


def ensure_dirs():
    """Create data directories if they don't exist."""
    for d in [cfg.INPUT_DIR, cfg.OUTPUT_DIR, cfg.INTERMEDIATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def run_all():
    """Run the complete pipeline: A1 → B → C → D"""
    logger = logging.getLogger("pipeline")
    logger.info("Starting full pipeline")

    results = {}
    step_funcs = [
        ("A-1", "expected", step_a1.run),
        ("B",   "selected_signals", step_b.run),
        ("C",   "unexpected", step_c.run),
        ("D",   "opportunities", step_d.run),
    ]
    for label, key, func in step_funcs:
        try:
            result = func()
            if result is None:
                logger.error(f"Step {label} returned None — treating as empty list")
                result = []
            results[key] = result
            logger.info(f"  {label}: {len(result)} items")
            if not result:
                logger.warning(f"⚠ Step {label} produced 0 results — downstream steps may fail")
        except Exception:
            logger.exception(f"Step {label} FAILED")
            results[key] = []
            logger.error(f"⚠ Continuing pipeline after {label} failure (downstream steps may produce degraded output)")

    logger.info("=" * 60)
    logger.info("Pipeline complete!")
    logger.info(f"  A-1: {len(results.get('expected', []))} Expected Scenarios")
    logger.info(f"  B:   {len(results.get('selected_signals', []))} Selected Weak Signals")
    logger.info(f"  C:   {len(results.get('unexpected', []))} Unexpected Scenarios")
    logger.info(f"  D:   {len(results.get('opportunities', []))} Opportunity Scenarios")
    logger.info(f"  Output: {cfg.OUTPUT_DIR}")
    logger.info("=" * 60)

    save_cost_report()


def clear_checkpoints(step: str, phase: int = None):
    """Remove checkpoint files for a given step so it runs from scratch.

    If phase is specified (for steps that support it, e.g. a1), only clear
    the checkpoint for that specific phase instead of all phases.
    """
    logger = logging.getLogger("pipeline")
    prefix_map = {
        "a1": ["a1_phase1_checkpoint", "a1_phase2_checkpoint", "a1_phase3_checkpoint"],
        "b":  ["b_phase1_checkpoint"],
        "c":  ["c_phase1_checkpoint", "c_phase2_checkpoint"],
        "d":  ["d_phase1_pairs", "d_phase2_checkpoint"],
        "all": [
            "a1_phase1_checkpoint", "a1_phase2_checkpoint", "a1_phase3_checkpoint",
            "b_phase1_checkpoint",
            "c_phase1_checkpoint", "c_phase2_checkpoint",
            "d_phase1_pairs", "d_phase2_checkpoint",
        ],
    }
    # If a specific phase is given, only clear that phase's checkpoint
    if phase is not None and step in ("a1", "c"):
        targets = [f"{step}_phase{phase}_checkpoint"]
    else:
        targets = prefix_map.get(step, [])
    for name in targets:
        path = cfg.INTERMEDIATE_DIR / f"{name}.json"
        if path.exists():
            path.unlink()
            logger.info(f"  Cleared checkpoint: {path.name}")


def main():
    parser = argparse.ArgumentParser(description="JRI AI Scenario Pipeline")
    parser.add_argument("--step", choices=["a1", "b", "c", "d", "all"],
                        default="all", help="Which step to run")
    parser.add_argument("--phase", type=int, default=None,
                        help="For A-1: run specific phase (1, 2, 3, or 4)")
    parser.add_argument("--fresh", action="store_true",
                        help="Clear checkpoints before running (ignore previous progress)")
    args = parser.parse_args()

    setup_logging()
    ensure_dirs()

    if args.fresh:
        clear_checkpoints(args.step, phase=args.phase)

    if args.step == "all":
        run_all()
    elif args.step == "a1":
        if args.phase == 1:
            step_a1.phase1_summarize()
        elif args.phase == 2:
            step_a1.phase2_cluster()
        elif args.phase == 3:
            step_a1.phase3_generate()
        elif args.phase == 4:
            step_a1.phase4_rank()
        else:
            step_a1.run()
        save_cost_report()
    elif args.step == "b":
        step_b.run()
        save_cost_report()
    elif args.step == "c":
        step_c.run()
        save_cost_report()
    elif args.step == "d":
        step_d.run()
        save_cost_report()


if __name__ == "__main__":
    main()
