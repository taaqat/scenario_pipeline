"""
Pre-publication validation script for current JRI pipeline output.
Checks score integrity, gate thresholds, review flags, and cross-step linkage.

Usage:
    python3 validate_output.py
"""
import json
import logging
import sys
from collections import Counter
from pathlib import Path

import config as cfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = cfg.OUTPUT_DIR

# ── Helpers ──────────────────────────────────────────
def load_json(path: Path) -> list[dict]:
    if not path.exists():
        logger.warning(f"  File not found: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def report(level: str, check: str, msg: str):
    """Print a check result."""
    icon = {"PASS": "✅", "FAIL": "🔴", "WARN": "⚠️"}.get(level, "  ")
    print(f"  {icon} [{level}] {check}: {msg}")
    return level


results: list[str] = []


def load_primary_c_output() -> list[dict]:
    """Prefer full C output; fallback to C_used_in_D if only the derived subset exists."""
    c_full = load_json(OUTPUT_DIR / "C_unexpected_scenarios_ja.json")
    if c_full:
        return c_full
    return load_json(OUTPUT_DIR / "C_used_in_D_ja.json")


def normalize_ref_list(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def summarize_counter(counter: Counter) -> str:
    if not counter:
        return "0 flags"
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{key}={count}" for key, count in ordered)


def preview(items: list[str], limit: int = 5) -> str:
    if not items:
        return ""
    shown = items[:limit]
    suffix = "..." if len(items) > limit else ""
    return ", ".join(shown) + suffix


def _score_value(scenario: dict, key_spec) -> float:
    """Read score from one key or fallback key list."""
    if isinstance(key_spec, str):
        return scenario.get(key_spec, 0) or 0
    for key in key_spec:
        if key in scenario:
            return scenario.get(key, 0) or 0
    return 0


def check_dataset_score_sums(label: str, data: list[dict], dims: list[str]):
    if not data:
        results.append(report("WARN", f"{label} score sums", "No data found — skipped"))
        return

    mismatches = []
    for scenario in data:
        scenario_id = scenario.get("scenario_id", "?")
        total = scenario.get("total_score", 0)
        calc = sum(_score_value(scenario, dim) for dim in dims)
        if total != calc:
            mismatches.append(f"{scenario_id}: total={total} != sum={calc}")

    if mismatches:
        results.append(report("FAIL", f"{label} score sums", f"{len(mismatches)} mismatches: {preview(mismatches)}"))
    else:
        results.append(report("PASS", f"{label} score sums", f"All {len(data)} scenarios correct"))


def check_dataset_thresholds(label: str, data: list[dict], thresholds: dict[str, int]):
    if not data:
        results.append(report("WARN", f"{label} dim thresholds", "No data found — skipped"))
        return

    violations = []
    scenario_ids = []
    for scenario in data:
        scenario_id = scenario.get("scenario_id", "?")
        scenario_failed = False
        for dim, min_val in thresholds.items():
            val = scenario.get(dim, 0)
            if val < min_val:
                violations.append(f"{scenario_id}: {dim}={val} < {min_val}")
                scenario_failed = True

        if scenario_failed:
            scenario_ids.append(scenario_id)

    if violations:
        results.append(
            report(
                "FAIL",
                f"{label} dim thresholds",
                f"{len(violations)} violations across {len(scenario_ids)} scenarios: {preview(violations)}",
            )
        )
    else:
        results.append(report("PASS", f"{label} dim thresholds", f"All {len(data)} scenarios pass"))


# ── Check 1: Score sums ─────────────────────────────
def check_score_sums():
    """Verify total_score equals sum of dimension scores."""
    print("\n── Check 1: Score Sum Consistency ──")

    check_dataset_score_sums(
        "D",
        load_json(OUTPUT_DIR / "D_opportunity_scenarios_ja.json"),
        ["unexpected_score", "impact_score"],
    )
    check_dataset_score_sums(
        "C",
        load_primary_c_output(),
        [
            ("score_unexpectedness", "unexpectedness"),
            ("score_social_impact", "social_impact"),
            ("score_uncertainty", "uncertainty"),
        ],
    )
    check_dataset_score_sums(
        "A",
        load_json(OUTPUT_DIR / "A1_expected_scenarios_ja.json"),
        [
            ("score_structural_depth", "structural_depth"),
            ("score_irreversibility", "irreversibility"),
            ("score_industry_related", "industry_related"),
            ("score_topic_relevance", "topic_relevance"),
            ("score_feasibility", "feasibility"),
        ],
    )


# ── Check 2: Dimension thresholds ────────────────────
def check_dim_thresholds():
    """Verify selected scenarios meet minimum dimension scores."""
    print("\n── Check 2: Dimension Thresholds ──")

    # Plausibility is now a weighted dim, not a gate — no minimum threshold to check.
    check_dataset_thresholds(
        "D",
        load_json(OUTPUT_DIR / "D_opportunity_scenarios_ja.json"),
        {},
    )
    check_dataset_thresholds(
        "C",
        load_primary_c_output(),
        {},
    )
    check_dataset_thresholds(
        "A",
        load_json(OUTPUT_DIR / "A1_expected_scenarios_ja.json"),
        {},
    )


def check_review_flags():
    """Summarize current LLM review flags and verify duplicate references resolve."""
    print("\n── Check 3: Review Flags ──")

    datasets = [
        ("A", load_json(OUTPUT_DIR / "A1_expected_scenarios_ja.json")),
        ("C", load_primary_c_output()),
        ("D", load_json(OUTPUT_DIR / "D_opportunity_scenarios_ja.json")),
    ]

    for label, data in datasets:
        if not data:
            results.append(report("WARN", f"{label} review flags", "No data found — skipped"))
            continue

        known_ids = {scenario.get("scenario_id") for scenario in data}
        counts = Counter()
        invalid_refs = []
        flagged_ids = []

        for scenario in data:
            scenario_id = scenario.get("scenario_id", "?")
            flagged_here = False

            duplicate_of = scenario.get("review_duplicate_of")
            if duplicate_of:
                counts["duplicate"] += 1
                flagged_here = True
                if duplicate_of not in known_ids:
                    invalid_refs.append(f"{scenario_id}→{duplicate_of}")

            if scenario.get("review_theme_overlap"):
                counts["theme_overlap"] += 1
                flagged_here = True
            if scenario.get("review_weak_source"):
                counts["weak_source"] += 1
                flagged_here = True
            if scenario.get("review_weak_logic"):
                counts["weak_logic"] += 1
                flagged_here = True
            if scenario.get("review_weak_collision"):
                counts["weak_collision"] += 1
                flagged_here = True

            if flagged_here:
                flagged_ids.append(scenario_id)

        if invalid_refs:
            results.append(report("FAIL", f"{label} review flags", f"{len(invalid_refs)} invalid duplicate refs: {preview(invalid_refs)}"))
        elif counts:
            results.append(
                report(
                    "WARN",
                    f"{label} review flags",
                    f"{summarize_counter(counts)} | review these IDs: {preview(flagged_ids)}",
                )
            )
        else:
            results.append(report("PASS", f"{label} review flags", "No review flags raised"))


def check_cross_step_links():
    """Verify B→C references, A/C→D references, and C_used_in_D export alignment."""
    print("\n── Check 4: Cross-Step References ──")

    b_data = load_json(OUTPUT_DIR / "B_selected_weak_signals_ja.json")
    c_full = load_json(OUTPUT_DIR / "C_unexpected_scenarios_ja.json")
    d_data = load_json(OUTPUT_DIR / "D_opportunity_scenarios_ja.json")
    a_data = load_json(OUTPUT_DIR / "A1_expected_scenarios_ja.json")
    c_used = load_json(OUTPUT_DIR / "C_used_in_D_ja.json")

    if b_data and c_full:
        b_ids = {str(signal.get("signal_id", "")) for signal in b_data if signal.get("signal_id")}
        c_missing = []
        c_empty = []
        c_untitled = []
        for scenario in c_full:
            scenario_id = scenario.get("scenario_id", "?")
            source_signals = normalize_ref_list(scenario.get("source_signals"))
            if not source_signals:
                c_empty.append(scenario_id)
                continue
            for signal in source_signals:
                signal_id = str(signal.get("signal_id", "")).strip()
                if signal_id and signal_id not in b_ids:
                    c_missing.append(f"{scenario_id}→B:{signal_id}")
                if not (signal.get("title") or signal.get("title_ja")):
                    c_untitled.append(f"{scenario_id}→B:{signal_id or '?'}")

        if c_missing:
            results.append(report("FAIL", "C source signals", f"{len(c_missing)} missing B refs: {preview(c_missing)}"))
        elif c_empty:
            results.append(report("FAIL", "C source signals", f"{len(c_empty)} scenarios missing source_signals: {preview(c_empty)}"))
        elif c_untitled:
            results.append(report("WARN", "C source signals", f"{len(c_untitled)} refs missing titles: {preview(c_untitled)}"))
        else:
            results.append(report("PASS", "C source signals", f"All {len(c_full)} C scenarios link cleanly to B"))
    else:
        results.append(report("WARN", "C source signals", "B or C output missing — skipped"))

    if a_data and d_data:
        a_ids = {scenario.get("scenario_id") for scenario in a_data}
        c_ids = {scenario.get("scenario_id") for scenario in (c_full or c_used)}
        d_missing = []
        d_empty = []
        used_c_ids = set()

        for scenario in d_data:
            scenario_id = scenario.get("scenario_id", "?")
            expected_refs = normalize_ref_list(scenario.get("selected_expected"))
            unexpected_refs = normalize_ref_list(scenario.get("selected_unexpected"))

            if not expected_refs or not unexpected_refs:
                d_empty.append(scenario_id)

            for ref in expected_refs:
                ref_id = ref.get("id", "")
                if ref_id and ref_id not in a_ids:
                    d_missing.append(f"{scenario_id}→A:{ref_id}")
            for ref in unexpected_refs:
                ref_id = ref.get("id", "")
                if ref_id:
                    used_c_ids.add(ref_id)
                    if ref_id not in c_ids:
                        d_missing.append(f"{scenario_id}→C:{ref_id}")

        if d_missing:
            results.append(report("FAIL", "D source IDs", f"{len(d_missing)} missing refs: {preview(d_missing)}"))
        elif d_empty:
            results.append(report("FAIL", "D source IDs", f"{len(d_empty)} scenarios missing selected inputs: {preview(d_empty)}"))
        else:
            results.append(report("PASS", "D source IDs", "All D references resolve to current A/C outputs"))

        if c_used:
            c_used_ids = {scenario.get("scenario_id") for scenario in c_used}
            missing_in_used = sorted(used_c_ids - c_used_ids)
            extra_in_used = sorted(c_used_ids - used_c_ids)
            if missing_in_used or extra_in_used:
                details = []
                if missing_in_used:
                    details.append(f"missing={preview(missing_in_used)}")
                if extra_in_used:
                    details.append(f"extra={preview(extra_in_used)}")
                results.append(report("FAIL", "C_used_in_D sync", "; ".join(details)))
            else:
                results.append(report("PASS", "C_used_in_D sync", f"Matches D references exactly ({len(c_used_ids)} scenarios)"))
        else:
            results.append(report("WARN", "C_used_in_D sync", "C_used_in_D_ja.json not found — skipped"))
    else:
        results.append(report("WARN", "D source IDs", "A or D output missing — skipped"))
        results.append(report("WARN", "C_used_in_D sync", "D or C_used_in_D output missing — skipped"))


# ── Check 5: Unexpectedness-plausibility gap ──────────
def check_collision_plausibility_gap():
    """Flag D scenarios where unexpectedness greatly exceeds plausibility_score."""
    print("\n── Check 5: Unexpectedness vs Plausibility Gap ──")

    d_data = load_json(OUTPUT_DIR / "D_opportunity_scenarios_ja.json")
    flagged = []
    for s in d_data:
        sid = s.get("scenario_id", "?")
        col = s.get("unexpected_score", 0)
        plau = s.get("plausibility_score", 0)
        if col > plau + 3:
            flagged.append(f"{sid}: unexpected={col}, plausibility={plau}")

    if flagged:
        results.append(report("WARN", "Unexpected-plausibility gap", f"{len(flagged)} flagged: {', '.join(flagged[:5])}"))
    else:
        results.append(report("PASS", "Unexpected-plausibility gap", "No concerning gaps"))


# ── Main ─────────────────────────────────────────────
def main():
    print("=" * 60)
    print("JRI Pipeline Output Validation")
    print("=" * 60)

    check_score_sums()
    check_dim_thresholds()
    check_review_flags()
    check_cross_step_links()
    check_collision_plausibility_gap()

    print("\n" + "=" * 60)
    fails = sum(1 for r in results if r == "FAIL")
    warns = sum(1 for r in results if r == "WARN")
    passes = sum(1 for r in results if r == "PASS")
    print(f"Summary: {passes} PASS, {warns} WARN, {fails} FAIL")
    if fails:
        print("⚠️  FAIL items must be fixed before publication.")
    print("=" * 60)

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
