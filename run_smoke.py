"""End-to-end smoke run with small N values. Runs B score+dedup → A1 → C → D."""
import logging
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from config import apply_overrides

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("smoke")

t0 = time.time()

def banner(name):
    log.info("=" * 70)
    log.info(f"▶ {name}  (elapsed {int(time.time()-t0)}s)")
    log.info("=" * 70)

def _clear_stale_smoke_checkpoints():
    """Avoid cross-run contamination in smoke mode by clearing high-risk checkpoints."""
    names = [
        "a1_phase3_checkpoint.json",
        "c_phase2_checkpoint.json",
        "d_phase1_pairs.json",
        "d_phase2_checkpoint.json",
    ]
    removed = 0
    for name in names:
        p = cfg.INTERMEDIATE_DIR / name
        if p.exists():
            p.unlink()
            removed += 1
            log.info(f"cleared checkpoint: {p.name}")
    log.info(f"checkpoint cleanup done: removed {removed}/{len(names)} files")


def main():
    # ── Smoke override: small N so the run finishes in minutes ──
    apply_overrides({
        "B_TOP_N": 500,
        "A1_GENERATE_N": 10,
        "C_GENERATE_N": 20,
        "D_GENERATE_N": 10,
    })

    _clear_stale_smoke_checkpoints()

    banner("Step B — score + rank + diversity dedup")
    from steps.step_b import run as run_b
    run_b()

    banner("Step A1 — cluster + generate 10 + rank")
    from steps.step_a1 import phase2_cluster, phase3_generate, phase4_rank
    themes = phase2_cluster()
    scenarios = phase3_generate(themes)
    phase4_rank(scenarios)

    banner("Step C — cluster_pair + generate 20 + rank")
    from steps.step_c import run as run_c
    run_c()

    banner("Step D — pair + generate 10 + rank")
    from steps.step_d import run as run_d
    run_d()

    banner(f"DONE — total elapsed {int(time.time()-t0)}s")


if __name__ == "__main__":
    main()
