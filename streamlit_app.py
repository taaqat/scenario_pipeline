"""
AI Scenario Pipeline — Streamlit Web UI
========================================
Setup → ① Expected → ② Weak Signals → ③ Unexpected → ④ Opportunities → Results

Run:
    streamlit run streamlit_app.py
"""
import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from config import UI_PARAMS, apply_overrides
from utils.data_io import read_json, save_json
from utils.llm_client import get_client
from utils.openai_client import get_openai_client

logger = logging.getLogger("pipeline")


# ─── Auth ───────────────────────────────────────────────
# Single-password gate. Credentials come from env vars (or Streamlit Cloud
# secrets, which are also exposed as env vars). When neither is set the gate
# is disabled — convenient for local dev, but the deploy MUST set both.
APP_USER = os.getenv("APP_USER", "")
APP_PASS = os.getenv("APP_PASS", "")
AUTH_REQUIRED = bool(APP_USER and APP_PASS)


def _check_credentials(u: str, p: str) -> bool:
    # compare_digest avoids timing attacks; overkill for a single shared pass
    # but cheap and removes a class of theoretical issues.
    return (
        secrets.compare_digest(u or "", APP_USER)
        and secrets.compare_digest(p or "", APP_PASS)
    )


def render_login():
    """Login page — full-screen form. Only shown when AUTH_REQUIRED and the
    user hasn't authenticated yet in this session."""
    st.markdown(
        "<div style='max-width:380px; margin:5rem auto; text-align:center'>"
        "<h2 style='margin-bottom:0.25rem'>🔮 AI Scenario Pipeline (JRI x Living Lab+)</h2>"
        "<div style='color:#6b7280; font-size:0.9rem; margin-bottom:2rem'>Sign in to continue</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    _, col, _ = st.columns([1, 2, 1])
    with col:
        with st.form("login_form", clear_on_submit=False, border=True):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if ok:
            if _check_credentials(u, p):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Invalid username or password.")


# ─── Page Config ────────────────────────────────────────
st.set_page_config(
    page_title="AI Scenario Pipeline (JRI x Living Lab+)",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1100px; }
    h1, h2, h3 { color: #1f2937; }
    .scn-step-header {
        display: flex; align-items: center; gap: 0.5rem;
        margin-bottom: 0.25rem;
    }
    .scn-step-title { font-size: 1.15rem; font-weight: 600; color: #1f2937; }
    .scn-step-sub { font-size: 0.85rem; color: #6b7280; margin-bottom: 0.5rem; }
    .scn-info {
        background: #eef2ff;
        border-left: 3px solid #6366f1;
        padding: 0.5rem 0.75rem;
        border-radius: 6px;
        font-size: 0.85rem;
        color: #4338ca;
        margin-bottom: 0.75rem;
    }
    /* Hide hamburger noise */
    [data-testid="stToolbar"] { visibility: hidden; }
    footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ─── Step metadata ──────────────────────────────────────
STEPS = {
    "A1": {
        "key": "run_a1",
        "label": "① Expected Scenarios",
        "title": "Expected Scenarios",
        "sub": "Identify structural changes from news articles",
        "icon": "📊",
        "color": "#1976D2",
        "accent": "a1",
        "section": "A1 Expected",
        "tab_label": "① Expected",
    },
    "B": {
        "key": "run_b",
        "label": "② Weak Signals",
        "title": "Weak Signals",
        "sub": "Score and select emerging signals",
        "icon": "📡",
        "color": "#00897B",
        "accent": "b",
        "section": "B Weak Signal",
        "tab_label": "② Weak Signals",
    },
    "C": {
        "key": "run_c",
        "label": "③ Unexpected Scenarios",
        "title": "Unexpected Scenarios",
        "sub": "Generate surprising future scenarios from signals",
        "icon": "🔮",
        "color": "#F57C00",
        "accent": "c",
        "section": "C Unexpected",
        "tab_label": "③ Unexpected",
    },
    "D": {
        "key": "run_d",
        "label": "④ Opportunities",
        "title": "Opportunities",
        "sub": "Discover business opportunities by combining expected and unexpected scenarios",
        "icon": "💡",
        "color": "#7B1FA2",
        "accent": "d",
        "section": "D Opportunity",
        "tab_label": "④ Opportunities",
    },
}

# Params hidden from UI (translation removed; SMOKE_TEST is dev-only)
HIDDEN_PARAMS = {"TRANSLATE_ENABLED"}

# Output filename pattern per step (used for ✓ markers + download buttons)
STEP_OUTPUT = {
    "run_a1": "A1_expected_scenarios",
    "run_b":  "B_selected_weak_signals",
    "run_c":  "C_unexpected_scenarios",
    "run_d":  "D_opportunity_scenarios",
}

# ┌─────────────────────────────────────────────────────────────────┐
# │  SACRED CACHES — must NEVER be deleted by any UI action.        │
# │                                                                 │
# │  These files represent hours of API time (~$50+ each) and the   │
# │  UI is intentionally read-only with respect to them:            │
# │                                                                 │
# │  - a1_phase1_summaries.json: LLM summaries of ~6,135 articles.  │
# │  - b_phase1_scored.json: LLM scores for ~9,004 weak signals.    │
# │  - matching *_checkpoint.json so an interrupted CLI run can     │
# │    resume from the last batch.                                  │
# │                                                                 │
# │  Defenses:                                                      │
# │  - run_a1 / run_b paths in run_step() never import the LLM      │
# │    functions that would regenerate these files.                 │
# │  - check_prerequisites() blocks Run if any sacred cache is      │
# │    missing.                                                     │
# │  - archive_step_outputs() filters them from any delete list.    │
# │  - sync_sacred_backups() mirrors them to ~/.cache and auto-     │
# │    restores from backup if the primary copy goes missing.       │
# │                                                                 │
# │  Regeneration only via the CLI:                                 │
# │      python run_pipeline.py --step a1 --phase 1                 │
# │      python run_pipeline.py --step b  --phase 1                 │
# └─────────────────────────────────────────────────────────────────┘
SACRED_CACHES: frozenset[str] = frozenset({
    "a1_phase1_summaries.json",
    "a1_phase1_checkpoint.json",
    "b_phase1_scored.json",
    "b_phase1_checkpoint.json",
})


# Process-wide run gate. st.session_state.running is per-tab, so two browser
# tabs would otherwise both pass the "is anything running" check and spawn
# concurrent workers that race on the same output files.
_RUN_LOCK = threading.Lock()
_RUN_GATE = {"running": False, "step": None}


# Mirror destination for sacred caches. Lives outside the project tree so a
# `rm -rf` of the repo, a `git clean -fdx`, or a fresh deploy that forgets to
# copy data/intermediate/ doesn't lose both copies at once.
def _sacred_backup_dir() -> Path:
    return Path.home() / ".cache" / "scenario_pipeline_sacred" / cfg.OUTPUT_DIR.name


def sync_sacred_backups() -> None:
    """Two-way sync of sacred phase-1 caches between data/intermediate/ and a
    user-home mirror.

    Called once at app startup. Behaviour:
      - primary newer than mirror → copy to mirror (keep the safety net fresh)
      - primary missing, mirror present → RESTORE from mirror (loud log)
      - both missing → leave alone; check_prerequisites() will block any Run
        and tell the user to contact the LivingLab+ team

    This guards against the most common loss vectors: an accidental `rm`,
    a `git clean`, or a deploy that didn't carry data/intermediate/. It does
    NOT protect against losing the user's home directory or the whole disk —
    for that, also keep an off-machine copy (e.g. JRI shared drive).
    """
    backup_dir = _sacred_backup_dir()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        cfg.INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"sacred-backup: cannot prepare directories: {e}")
        return

    def _atomic_copy(src: Path, dst: Path) -> None:
        # tmp + os.replace prevents a concurrent tab from observing a
        # half-written dst and copying it back over a good src.
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)

    for fn in SACRED_CACHES:
        primary = cfg.INTERMEDIATE_DIR / fn
        mirror = backup_dir / fn
        try:
            if primary.exists():
                # Keep mirror up to date. The 1s slack avoids spurious copies
                # on filesystems with coarse mtime resolution.
                if not mirror.exists() or primary.stat().st_mtime > mirror.stat().st_mtime + 1:
                    _atomic_copy(primary, mirror)
                    logger.info(f"sacred-backup: synced {fn} → {backup_dir}")
            elif mirror.exists():
                _atomic_copy(mirror, primary)
                logger.warning(
                    f"sacred-backup: RESTORED {fn} from {backup_dir} — "
                    f"the primary copy in {cfg.INTERMEDIATE_DIR} was missing. "
                    f"This usually means someone cleaned the data/ directory; "
                    f"please confirm the file is intact and tell the LivingLab+ team."
                )
        except Exception as e:
            logger.warning(f"sacred-backup: {fn} sync/restore failed: {e}")


# ─── Cumulative cost tracking ────────────────────────────────────────
# Per-run cost_report.json is written by run_pipeline.save_cost_report() and
# overwritten on each step. We keep a separate cumulative file under OUTPUT_DIR
# so the client sees total spend over time, not just the latest run.

def _cum_cost_file() -> Path:
    return cfg.OUTPUT_DIR / "cost_report_cumulative.json"


def _step_bucket(phase_key: str) -> str:
    """Map per-phase keys (e.g. 'A1-cluster', 'B-diversity') into the four
    client-facing step buckets. Phase-level detail is intentionally hidden."""
    p = phase_key.upper()
    if p.startswith("A1") or p.startswith("A-1"): return "A1"
    if p.startswith("B"): return "B"
    if p.startswith("C"): return "C"
    if p.startswith("D"): return "D"
    return "other"


def merge_run_into_cumulative() -> None:
    """Read the latest cost_report.json (per-run) and add it into
    cost_report_cumulative.json. Aggregates phase-level entries into the four
    step buckets so the UI doesn't expose internal phase names."""
    per_run = cfg.OUTPUT_DIR / "cost_report.json"
    if not per_run.exists():
        return
    try:
        cur = read_json(per_run) or {}
    except Exception:
        return

    cum_path = _cum_cost_file()
    cum = {"total": {}, "by_step": {}}
    if cum_path.exists():
        try:
            cum = read_json(cum_path) or cum
        except Exception:
            pass

    by_step = cum.get("by_step", {})
    for phase, v in (cur.get("by_step") or {}).items():
        bucket = _step_bucket(phase)
        prev = by_step.get(bucket, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        by_step[bucket] = {
            "calls":         prev.get("calls", 0)         + (v.get("calls") or 0),
            "input_tokens":  prev.get("input_tokens", 0)  + (v.get("input_tokens") or 0),
            "output_tokens": prev.get("output_tokens", 0) + (v.get("output_tokens") or 0),
            "cost_usd":      round(prev.get("cost_usd", 0) + (v.get("cost_usd") or 0), 4),
        }

    in_  = sum(v.get("input_tokens", 0)  for v in by_step.values())
    out_ = sum(v.get("output_tokens", 0) for v in by_step.values())
    cum["by_step"] = by_step
    cum["total"] = {
        "calls":         sum(v.get("calls", 0) for v in by_step.values()),
        "input_tokens":  in_,
        "output_tokens": out_,
        "total_tokens":  in_ + out_,
        "cost_usd":      round(sum(v.get("cost_usd", 0) for v in by_step.values()), 4),
    }

    try:
        cfg.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = cum_path.with_suffix(cum_path.suffix + ".tmp")
        save_json(cum, tmp)
        os.replace(tmp, cum_path)
    except Exception as e:
        logger.warning(f"merge_run_into_cumulative failed: {e}")


# ─── Persistence (so ✓ marks + last-run info survive page reload) ───────
def _summary_file():
    return cfg.INTERMEDIATE_DIR / "_last_run_summary.json"


def load_persisted_summaries() -> dict:
    p = _summary_file()
    if not p.exists():
        return {}
    try:
        data = read_json(p)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def persist_summary(key: str, summary: dict, at: str, duration_s: float | None):
    """Persist the latest run summary to disk so ✓ marks survive page reload.

    Writes atomically via tmp + os.replace so two browser tabs racing on the
    same file can't corrupt it (last-write-wins is acceptable; partial JSON is
    not).
    """
    try:
        data = load_persisted_summaries()
        data[key] = {**summary, "at": at, "duration_s": duration_s}
        cfg.INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
        target = _summary_file()
        tmp = target.with_suffix(target.suffix + ".tmp")
        save_json(data, tmp)
        os.replace(tmp, target)
    except Exception as e:
        logger.warning(f"persist_summary failed: {e}")


def step_output_exists(key: str) -> bool:
    base = STEP_OUTPUT.get(key)
    if not base:
        return False
    return (cfg.OUTPUT_DIR / f"{base}_ja.json").exists()


def all_steps_complete() -> bool:
    return all(step_output_exists(k) for k in STEP_OUTPUT)


@st.cache_data(show_spinner=False, max_entries=20)
def cached_read_bytes(path_str: str, mtime: float, size: int) -> bytes:
    """Cache download bytes keyed by (mtime, size); mtime alone is unsafe on
    filesystems with 1-second resolution (SMB, FAT)."""
    return Path(path_str).read_bytes()


def file_bytes_for_download(path: Path) -> bytes:
    """Convenience wrapper: pull file bytes through the cache."""
    s = path.stat()
    return cached_read_bytes(str(path), s.st_mtime, s.st_size)


def fmt_duration(seconds: float | int | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


# ─── Session state init ─────────────────────────────────
def init_state():
    """Initialize session_state once. UI_PARAMS values default from cfg."""
    defaults = {
        "TOPIC": cfg.TOPIC,
        "TIMEFRAME": cfg.TIMEFRAME,
        "INDUSTRIES": ", ".join(cfg.CLIENT_PROFILE.get("industries", [])),
    }
    for k, spec in UI_PARAMS.items():
        if k in HIDDEN_PARAMS:
            continue
        if k in st.session_state:
            continue
        if k in defaults:
            st.session_state[k] = defaults[k]
        else:
            st.session_state[k] = spec["default"]

    # Per-run state
    st.session_state.setdefault("running", False)
    st.session_state.setdefault("last_summary", {})    # step_key -> summary dict
    st.session_state.setdefault("last_run_at", {})     # step_key -> "YYYY-MM-DD HH:MM"
    st.session_state.setdefault("last_duration", {})   # step_key -> seconds
    st.session_state.setdefault("last_error", {})      # step_key -> str
    st.session_state.setdefault("ppt_status", "")
    # Live-progress state — written from worker thread, read by progress_panel fragment
    st.session_state.setdefault("run_progress", None)  # dict: step, phase_label, phase_num, phase_total, start_time
    st.session_state.setdefault("_last_running_seen", False)
    # Steps that completed *in this browser session* (vs. hydrated from disk
    # at page load). Used to default the preview expander to open right after
    # a fresh run, but collapsed for runs that happened before this session.
    st.session_state.setdefault("_ran_this_session", set())

    # Hydrate from disk on first load so ✓ marks and "Last run: 8m 32s" badges
    # survive page reloads + new sessions.
    if not st.session_state.get("_hydrated"):
        persisted = load_persisted_summaries()
        for key, blob in persisted.items():
            if not isinstance(blob, dict):
                continue
            st.session_state.last_summary[key] = {
                "count": blob.get("count", 0),
                "label": blob.get("label", ""),
                "previews": blob.get("previews") or [],
            }
            if blob.get("at"):
                st.session_state.last_run_at[key] = blob["at"]
            if blob.get("duration_s"):
                st.session_state.last_duration[key] = blob["duration_s"]
        st.session_state["_hydrated"] = True


# ─── Helpers ────────────────────────────────────────────
def collect_overrides() -> tuple[dict, list[str]]:
    """Pull current UI param values from session_state. Apply on Run.

    Returns ``(overrides_dict, validation_errors)``. Empty TOPIC / TIMEFRAME /
    INDUSTRIES would otherwise let a run proceed silently against a blank
    research context, producing meaningless LLM output. Reject up front with
    a clear message.
    """
    ov = {k: st.session_state[k] for k in UI_PARAMS if k in st.session_state and k not in HIDDEN_PARAMS}

    errors: list[str] = []
    if not (ov.get("TOPIC") or "").strip():
        errors.append("Topic cannot be empty.")
    if not (ov.get("TIMEFRAME") or "").strip():
        errors.append("Time horizon cannot be empty.")
    industries_raw = (ov.get("INDUSTRIES") or "").strip()
    if not industries_raw or not [s.strip() for s in industries_raw.split(",") if s.strip()]:
        errors.append("Industries cannot be empty.")

    return ov, errors


def render_param(key: str, spec: dict):
    """Render a single UI_PARAMS row. The widget reads/writes session_state[key]."""
    label = spec["label"]
    hint = spec.get("hint", "")
    typ = spec["type"]

    if typ == "number":
        # Weights (0–10 small range) get a slider — easier to see ratios at a
        # glance. Counts (B_TOP_N, etc.) stay as number_input.
        is_weight = "_WEIGHT_" in key
        if is_weight:
            st.slider(
                label,
                min_value=int(spec.get("min", 0)),
                max_value=int(spec.get("max", 10)),
                step=1,
                key=key,
                help=hint or None,
            )
        else:
            st.number_input(
                label,
                min_value=spec.get("min", 0),
                max_value=spec.get("max", 1_000_000),
                step=1,
                key=key,
                help=hint or None,
            )
    elif typ == "bool":
        st.toggle(label, key=key, help=hint or None)
    elif typ == "select":
        opts = spec["options"]  # dict of value -> label
        opt_keys = list(opts.keys())
        st.selectbox(
            label,
            options=opt_keys,
            format_func=lambda v: opts.get(v, v),
            key=key,
            help=hint or None,
        )
    elif typ == "text":
        st.text_input(label, key=key, help=hint or None)


def render_settings_section(section: str, exclude: set | None = None):
    """Render all UI_PARAMS in a given section: main first, advanced in expander."""
    exclude = (exclude or set()) | HIDDEN_PARAMS
    items = [(k, v) for k, v in UI_PARAMS.items() if v["section"] == section and k not in exclude]
    main = [(k, v) for k, v in items if v.get("priority") == "main"]
    adv = [(k, v) for k, v in items if v.get("priority") == "advanced"]

    for k, v in main:
        render_param(k, v)

    if adv:
        active = sum(
            1 for k, _ in adv
            if "_WEIGHT_" in k and (st.session_state.get(k, 0) or 0) > 0
        )
        with st.expander(f"⚙️ Scoring Weights ({active} active)", expanded=True):
            st.caption(
                "All weights equal (e.g. all 1, or all 10) gives the same ranking. "
                "Change the **ratios** between weights to shift the priority."
            )
            for k, v in adv:
                render_param(k, v)


# ─── Pipeline run helpers ───────────────────────────────
def archive_step_outputs(key: str):
    """Move a step's existing outputs into history/<ts>/, and invalidate downstream caches.

    Cascade: re-running upstream archives downstream too (matches main app).
    """
    prefix_map = {
        "run_a1": ["A1_expected_scenarios", "D_opportunity_scenarios", "C_used_in_D"],
        "run_b":  ["B_selected_weak_signals", "C_unexpected_scenarios", "D_opportunity_scenarios", "C_used_in_D"],
        "run_c":  ["C_unexpected_scenarios", "D_opportunity_scenarios", "C_used_in_D"],
        "run_d":  ["D_opportunity_scenarios", "C_used_in_D"],
    }
    inter_delete = {
        "run_a1": ["d_phase1_pairs.json", "d_phase2_scenarios.json", "d_phase2_checkpoint.json"],
        "run_b":  [
            "c_phase1_clusters.json", "c_phase2_scenarios.json", "c_phase2_checkpoint.json",
            "d_phase1_pairs.json", "d_phase2_scenarios.json", "d_phase2_checkpoint.json",
        ],
        "run_c":  ["d_phase1_pairs.json", "d_phase2_scenarios.json", "d_phase2_checkpoint.json"],
        "run_d":  [],
    }
    prefixes = prefix_map.get(key) or []
    out_dir = cfg.OUTPUT_DIR
    matches = [p for pf in prefixes for p in out_dir.glob(f"{pf}*") if p.is_file()]
    if matches:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_dir = out_dir / "history" / f"{ts}_{key}"
        archive_dir.mkdir(parents=True, exist_ok=True)
        for p in matches:
            try:
                shutil.move(str(p), str(archive_dir / p.name))
            except Exception as e:
                logger.warning(f"archive {p.name} failed: {e}")
        logger.info(f"Archived {len(matches)} file(s) to {archive_dir}")

    for fn in inter_delete.get(key, []):
        if fn in SACRED_CACHES:
            logger.error(
                f"archive_step_outputs: refusing to delete sacred cache {fn!r}."
            )
            continue
        p = cfg.INTERMEDIATE_DIR / fn
        if p.exists():
            try:
                p.unlink()
            except Exception as e:
                logger.warning(f"delete {fn} failed: {e}")


def check_prerequisites(key: str) -> tuple[bool, str | None]:
    """Guard upstream outputs exist before running.

    Two kinds of guards:
    1. Sacred phase-1 caches must exist (never regenerated from the UI).
    2. Upstream step output must exist (so this step has data to consume).
    """
    # ── Sacred phase-1 cache checks ────────────────────────
    # If these are missing, refuse to run — the front-end is NEVER allowed to
    # trigger phase-1 LLM regeneration (each costs hours and ~$50). The CLI
    # tool is the only legitimate path to recreate them.
    if key == "run_a1":
        sf = cfg.INTERMEDIATE_DIR / "a1_phase1_summaries.json"
        if not sf.exists():
            return False, (
                "Cannot run ①: an essential pre-processed data file is missing. "
                "Recreating it takes hours of AI work, so it can only be "
                "restored by the LivingLab+ team — please contact them."
            )
    if key == "run_b":
        bf = cfg.INTERMEDIATE_DIR / "b_phase1_scored.json"
        if not bf.exists():
            return False, (
                "Cannot run ②: an essential pre-processed data file is missing. "
                "Recreating it takes hours of AI work, so it can only be "
                "restored by the LivingLab+ team — please contact them."
            )

    # ── Upstream-output dependency checks ──────────────────
    if key == "run_d":
        a1 = cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json"
        c = cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json"
        missing = [p.name for p in (a1, c) if not p.exists()]
        if missing:
            return False, f"Run ① and ③ first — missing: {', '.join(missing)}"
        try:
            # Cheap size check — fragment polls run every 2s, can't read_json
            # multi-MB outputs that often. Real output is far larger than 10B.
            if a1.stat().st_size < 10:
                return False, "① output is empty — re-run Step ①."
            if c.stat().st_size < 10:
                return False, "③ output is empty — re-run Step ③."
        except Exception as e:
            return False, f"Could not read upstream outputs: {e}"
    elif key == "run_c":
        b_cache = cfg.INTERMEDIATE_DIR / "b_phase3_dedup_selected.json"
        if not b_cache.exists():
            return False, "Step ③ needs Step ② output — run ② first."
        b_meta = cfg.INTERMEDIATE_DIR / "b_phase3_dedup_selected.meta.json"
        if not b_meta.exists():
            return False, "Step ③ needs Step ② metadata — re-run ②."
        try:
            meta = read_json(b_meta)
            meta_topic = str(meta.get("topic", "") or "").strip()
            cur_topic = str(cfg.TOPIC or "").strip()
            # Both must be non-empty AND match. Without the non-empty guard,
            # two empty strings compare equal and we'd run with no topic.
            if not cur_topic:
                return False, "Topic is empty — fill it in on the Setup tab first."
            if not meta_topic or meta_topic != cur_topic:
                return False, "Step ③ needs Step ② re-run for the current Research Topic."
        except Exception as e:
            return False, f"Could not read Step ② metadata: {e}"
    return True, None


def build_summary(key: str) -> dict | None:
    """Build a post-run summary card data: count + title previews."""
    omap = {
        "run_a1": ("A1_expected_scenarios_ja.json", "scenarios", "title"),
        "run_b":  ("B_selected_weak_signals_ja.json", "signals", "title"),
        "run_c":  ("C_unexpected_scenarios_ja.json", "scenarios", "title"),
        "run_d":  ("D_opportunity_scenarios_ja.json", "opportunities", "opportunity_title"),
    }
    if key not in omap:
        return None
    fn, label, tk = omap[key]
    p = cfg.OUTPUT_DIR / fn
    if not p.exists():
        return None
    try:
        data = read_json(p)
    except Exception:
        return None
    if not data:
        return {"count": 0, "label": label, "previews": [], "skipped_titles": 0}
    limit = 50 if key == "run_b" else 10
    previews = []
    skipped = 0
    for it in data[:limit]:
        title = (it.get(tk) or it.get("title") or "").strip()
        if not title:
            skipped += 1
            continue
        entry = {"title": title}
        if key == "run_a1":
            frm = (it.get("change_from_keyword") or "").strip()
            to = (it.get("change_to_keyword") or "").strip()
            if frm or to:
                entry["shift"] = f"{frm} → {to}"
        previews.append(entry)
    return {
        "count": len(data),
        "label": label,
        "previews": previews,
        "skipped_titles": skipped,
    }


def run_step(key: str, ov: dict, phase_cb):
    """Execute a step end-to-end. `phase_cb(label, num, total)` is called between
    phases so the UI can show progress. Safe to call from a worker thread."""
    apply_overrides(ov)

    # Reset per-run cost trackers
    try:
        get_client().tracker.reset()
        get_openai_client().reset_usage()
    except Exception as e:
        logger.warning(f"cost-tracker reset failed: {e}")

    archive_step_outputs(key)

    if key == "run_a1":
        from steps.step_a1 import phase2_cluster, phase3_generate, phase4_rank
        phase_cb("① 1/3 — Clustering articles...", 1, 3)
        themes = phase2_cluster()
        phase_cb("① 2/3 — Generating scenarios...", 2, 3)
        scenarios = phase3_generate(themes)
        phase_cb("① 3/3 — Scoring, filtering, review...", 3, 3)
        phase4_rank(scenarios)

    elif key == "run_b":
        # ⚠ DO NOT add `score_signals()` to this UI execution path.
        #
        # `score_signals()` may silently re-LLM all 9,000+ weak signals if the
        # phase-1 checkpoint or scored cache is incomplete or has a stale
        # signature (e.g. after a prompt-template edit). That is hours of work
        # and ~$50 of API spend that should NEVER be triggered by a client
        # clicking a button. The b_phase1_scored.json cache is regenerated
        # only via the CLI:
        #
        #     python run_pipeline.py --step b --phase 1
        #
        # check_prerequisites() guards that the cache is present before we
        # reach this branch. The UI's job from here is just to re-rank and
        # de-duplicate the existing scores against the current weights.
        from steps.step_b import diversity_dedup
        phase_cb("② Ranking & de-duplicating signals (using cached LLM scores)...", 1, 1)
        diversity_dedup()

    elif key == "run_c":
        from steps.step_c import phase1_cluster, phase1_cluster_pair, phase1_signal_pair, phase2_generate, phase3_rank
        phase_cb("③ 1/3 — Grouping signals...", 1, 3)
        if cfg.C_MODE == "cluster_pair":
            cl = phase1_cluster_pair()
        elif cfg.C_MODE == "signal_pair":
            cl = phase1_signal_pair()
        else:
            cl = phase1_cluster()
        phase_cb("③ 2/3 — Generating scenarios...", 2, 3)
        sc = phase2_generate(cl)
        phase_cb("③ 3/3 — Scoring & ranking...", 3, 3)
        phase3_rank(sc)

    elif key == "run_d":
        from steps.step_d import phase1_random_pairs, phase2_generate, phase3_rank
        exp = read_json(cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json")
        unexp = read_json(cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json")
        phase_cb("④ 1/3 — Pairing scenarios...", 1, 3)
        pairs = phase1_random_pairs(exp, unexp)
        phase_cb("④ 2/3 — Generating opportunities...", 2, 3)
        sc = phase2_generate(pairs, exp, unexp)
        phase_cb("④ 3/3 — Scoring, filtering, classifying...", 3, 3)
        phase3_rank(sc)

    # Save per-run cost report
    try:
        from run_pipeline import save_cost_report
        save_cost_report()
    except Exception as e:
        logger.warning(f"save_cost_report failed: {e}")


# ─── Step tab rendering ─────────────────────────────────
STEP_NAV = {
    "A1": {"prev": "Setup",          "next": "② Weak Signals"},
    "B":  {"prev": "① Expected",     "next": "③ Unexpected"},
    "C":  {"prev": "② Weak Signals", "next": "④ Opportunities"},
    "D":  {"prev": "③ Unexpected",   "next": "Results"},
}


def render_step_tab(code: str, description_md: str, note: str | None = None):
    info = STEPS[code]
    key = info["key"]
    color = info["color"]

    # Header
    st.markdown(
        f'<div class="scn-step-header">'
        f'<span style="font-size:1.4rem">{info["icon"]}</span>'
        f'<span class="scn-step-title" style="color:{color}">{info["title"]}</span>'
        f'</div>'
        f'<div class="scn-step-sub">{info["sub"]}</div>',
        unsafe_allow_html=True,
    )

    if note:
        st.markdown(f'<div class="scn-info">{note}</div>', unsafe_allow_html=True)

    # "What this step does" — short description, collapsed by default to keep
    # the page scannable; the help text is one click away.
    with st.expander("📖 What this step does", expanded=False):
        st.markdown(description_md)

    # Settings card
    with st.container(border=True):
        st.markdown("**Settings**")
        render_settings_section(info["section"])

    # ─── Run controls ───────────────────────────────────────
    running = st.session_state.get("running", False)
    ok, prereq_err = check_prerequisites(key)
    last_dur = st.session_state.last_duration.get(key)

    run_label = "▶  Run this step"
    if last_dur:
        run_label += f"   ·   last run: {fmt_duration(last_dur)}"

    run_disabled = running or not ok
    clicked = st.button(
        run_label,
        key=f"runbtn_{key}",
        type="primary",
        use_container_width=True,
        disabled=run_disabled,
    )
    if not ok and prereq_err:
        st.warning(prereq_err)
    if clicked:
        execute_run(key)
        st.rerun()

    # ─── Live progress card (only when this step is running) ───
    # Accent matches the step (① blue / ② teal / ③ orange / ④ purple) so the
    # running state visually stands out against the grey settings cards.
    step_progress_card(key, accent=color)

    # ─── Last-run result card ──────────────────────────────────
    summary = st.session_state.last_summary.get(key)
    last_at = st.session_state.last_run_at.get(key)
    err = st.session_state.last_error.get(key)

    if err:
        with st.container(border=True):
            st.error(f"❌ Last run failed: {err[:300]}")
            st.markdown(
                "**What you can try:**\n"
                "- Lower the count parameter (e.g. *Number of scenarios*) and try again\n"
                "- Verify the **Setup** tab — Topic / Time horizon / Industries should not be empty\n"
                "- If failure persists, share the log file with the LivingLab+ team"
            )
    elif summary and last_at:
        with st.container(border=True):
            count_line = f"✓ Done — **{summary['count']} {summary['label']}**"
            meta_line = f"at {last_at}"
            if last_dur:
                meta_line += f" · took {fmt_duration(last_dur)}"
            st.markdown(count_line)
            st.caption(meta_line)

            skipped = summary.get("skipped_titles", 0) or 0
            if skipped:
                st.warning(
                    f"⚠ {skipped} item(s) in the preview had no title and "
                    "were skipped — this usually means the AI returned bad "
                    "data. The total count still includes them; open the "
                    "JSON download to inspect."
                )

            # Inline downloads — saves a trip to the Results tab
            base = STEP_OUTPUT.get(key)
            if base:
                ja = cfg.OUTPUT_DIR / f"{base}_ja.json"
                xlsx = cfg.OUTPUT_DIR / f"{base}.xlsx"
                dcols = st.columns(3)
                if xlsx.exists():
                    dcols[0].download_button(
                        "📥 Excel",
                        data=file_bytes_for_download(xlsx),
                        file_name=xlsx.name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"step_dl_xlsx_{key}",
                        use_container_width=True,
                    )
                if ja.exists():
                    dcols[1].download_button(
                        "📥 JSON",
                        data=file_bytes_for_download(ja),
                        file_name=ja.name,
                        mime="application/json",
                        key=f"step_dl_json_{key}",
                        use_container_width=True,
                    )

            # Preview expanded if the run just happened in this session;
            # collapsed if hydrated from disk on first page load (less noisy).
            previews = summary.get("previews") or []
            preview_open = key in st.session_state.get("_ran_this_session", set())
            if previews:
                with st.expander(f"Preview titles ({len(previews)})", expanded=preview_open):
                    for i, pv in enumerate(previews, 1):
                        st.markdown(f"**{i}.** {pv['title']}")
                        if pv.get("shift"):
                            st.caption(pv["shift"])
            if key == "run_d":
                st.caption("→ See the **Opportunity Matrix** in the Results tab.")

    # ─── Bottom prev/next hints ──────────────────────────────
    nav = STEP_NAV.get(code)
    if nav:
        # Plain-text hint, NOT clickable. Streamlit's st.tabs has no API for
        # programmatic tab switching, so we just remind the user where to
        # click in the tab bar at the top of the page.
        st.markdown(
            f"<div style='margin-top:1.5rem;text-align:center;"
            f"font-size:0.75rem;color:#9ca3af;line-height:1.5'>"
            f"<span style='display:inline-block;padding:0 0.5rem'>← Previous: <b>{nav['prev']}</b></span>"
            f"<span style='display:inline-block;padding:0 0.5rem'>Next: <b>{nav['next']}</b> →</span>"
            f"<br><span style='font-size:0.7rem;font-style:italic'>"
            f"(use the tab bar at the top of the page to switch)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


def execute_run(key: str):
    """Spawn a worker thread for the pipeline step. Returns immediately so the
    UI stays responsive; the progress_panel fragment polls run_progress for
    live updates and triggers a full rerun when the worker finishes.

    _RUN_LOCK + _RUN_GATE prevent double-spawn from rapid clicks or a second
    browser tab — both would otherwise race through archive_step_outputs.
    """
    ov, errors = collect_overrides()
    if errors:
        st.error("Cannot run: " + " ".join(errors) + " Please fix in the **Setup** tab.")
        return

    with _RUN_LOCK:
        if _RUN_GATE["running"] or st.session_state.get("running"):
            busy = (_RUN_GATE.get("step") or "").removeprefix("run_").upper()
            label = STEPS.get(busy, {}).get("label", "another step")
            st.warning(f"Already running — please wait for {label} to finish.")
            return
        _RUN_GATE["running"] = True
        _RUN_GATE["step"] = key
        st.session_state.running = True

    st.session_state.last_error.pop(key, None)
    st.session_state.last_summary.pop(key, None)
    st.session_state.run_progress = {
        "step": key,
        "phase_label": "Starting...",
        "phase_num": 0,
        "phase_total": 0,
        "start_time": time.time(),
    }

    session = st.session_state  # capture binding for thread closure

    def _phase_cb(label: str, num: int = 0, total: int = 0):
        prev = session.get("run_progress") or {}
        session.run_progress = {
            "step": key,
            "phase_label": label,
            "phase_num": num,
            "phase_total": total,
            "start_time": prev.get("start_time", time.time()),
        }

    def _worker():
        t0 = time.time()
        try:
            run_step(key, ov, _phase_cb)
            duration = time.time() - t0
            # run_step has just refreshed cost_report.json with this run only;
            # add it into the cumulative file the UI shows the client.
            merge_run_into_cumulative()
            summary = build_summary(key)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            if summary is not None:
                session.last_summary[key] = summary
            session.last_run_at[key] = stamp
            session.last_duration[key] = duration
            session._ran_this_session.add(key)
            if summary is not None:
                persist_summary(key, summary, stamp, duration)
        except Exception as e:
            logger.exception(f"{key} failed")
            session.last_error[key] = f"{type(e).__name__}: {e}"
        finally:
            session.running = False
            session.run_progress = None
            with _RUN_LOCK:
                _RUN_GATE["running"] = False
                _RUN_GATE["step"] = None

    t = threading.Thread(target=_worker, daemon=True)
    # CRITICAL: attach Streamlit script-run context so the thread can safely
    # write to st.session_state. Without this, writes silently miss the user's
    # session.
    add_script_run_ctx(t)
    t.start()


# ─── Live progress panels (auto-refresh every 2s while running) ─────────
# Two fragments: a tiny header badge that shows across all tabs, and a full
# progress card rendered inline below each step's Run button so clicking Run
# doesn't scroll the user to the top of the page.

@st.fragment(run_every="2s")
def header_running_badge():
    """Compact 'Running ① 1/3 — ...' line in the header area, visible across
    all tabs. Triggers a full app rerun once when the worker finishes so the
    step preview shows up automatically."""
    running = st.session_state.get("running", False)
    last_seen = st.session_state.get("_last_running_seen", False)

    if running:
        st.session_state["_last_running_seen"] = True
        p = st.session_state.get("run_progress") or {}
        elapsed = int(time.time() - p.get("start_time", time.time()))
        mins, secs = divmod(elapsed, 60)
        st.markdown(
            f"<div style='font-size:0.8rem;color:#b45309;background:#fffbeb;"
            f"border:1px solid #fde68a;border-radius:6px;padding:0.35rem 0.6rem;"
            f"margin-bottom:0.5rem'>"
            f"⏱ <b>Running</b> · {p.get('phase_label', '')} · {mins}m {secs:02d}s"
            f"</div>",
            unsafe_allow_html=True,
        )
        return

    if last_seen:
        st.session_state["_last_running_seen"] = False
        st.rerun()


@st.fragment(run_every="2s")
def step_progress_card(step_key: str, accent: str = "#6366f1"):
    """Big progress card with phase label + bar + elapsed. Renders only when
    the currently-running step matches `step_key`, so each tab shows its own
    card inline below the Run button. `accent` is the step's color so the
    running state visually pops against the grey settings cards above."""
    if not st.session_state.get("running"):
        return
    p = st.session_state.get("run_progress") or {}
    if p.get("step") != step_key:
        return
    elapsed = int(time.time() - p.get("start_time", time.time()))
    mins, secs = divmod(elapsed, 60)
    # Outer wrapper carries the per-step accent so the running card is
    # visually distinct from the grey-bordered settings card.
    st.markdown(
        f"<div style='border:1px solid {accent}; border-left:4px solid {accent}; "
        f"background:{accent}0d; border-radius:8px; padding:0.8rem 1rem; margin:0.5rem 0'>"
        f"<div style='color:{accent}; font-weight:600; margin-bottom:0.25rem'>"
        f"⏱ Running… {p.get('phase_label', '')}"
        f"</div>",
        unsafe_allow_html=True,
    )
    total = p.get("phase_total", 0) or 0
    num = p.get("phase_num", 0) or 0
    if total > 1:
        st.progress(min(num / total, 1.0))
    st.markdown(
        f"<div style='font-size:0.8rem; color:#6b7280; margin-top:0.4rem'>"
        f"Elapsed: {mins}m {secs:02d}s · auto-refreshes every 2s · "
        f"you can switch tabs while it runs."
        f"</div></div>",
        unsafe_allow_html=True,
    )


# ─── Setup tab ──────────────────────────────────────────
def render_setup():
    st.markdown("### Setup")
    st.caption(
        "Configure your analysis settings here, then move through "
        "**① → ② → ③ → ④** in the tabs above to generate your scenarios."
    )

    with st.container(border=True):
        st.markdown("#### 🌐 Research Settings")
        st.caption("These settings affect all steps. Adjust before running.")
        render_settings_section("Global", exclude={"TRANSLATE_ENABLED"})

    with st.container(border=True):
        st.markdown("#### 📁 Data")
        st.caption(
            "These datasets are pre-loaded by JRI for this engagement and "
            "cannot be modified from this UI."
        )
        DISPLAY_COUNTS = {"News articles": 6135, "Weak signals": 9004}
        for f, label in [(cfg.A1_INPUT_FILE, "News articles"), (cfg.B_INPUT_FILE, "Weak signals")]:
            count = DISPLAY_COUNTS.get(label)
            if count is None:
                try:
                    import pandas as pd
                    if Path(f).suffix == ".xlsx" and Path(f).exists():
                        count = len(pd.read_excel(f))
                except Exception:
                    pass
            line = f"✓ {label}"
            if count:
                line += f" — {count:,} items"
            st.markdown(line)

    # CTA at the bottom — Streamlit doesn't let us programmatically switch
    # tabs, but a clear pointer to the next step still helps first-time users.
    st.markdown(
        "<div style='margin-top:1.25rem;padding:0.75rem 1rem;"
        "background:#eef2ff;border-left:3px solid #6366f1;border-radius:8px;"
        "font-size:0.9rem;color:#4338ca'>"
        "<b>Ready?</b> Click the <b>① Expected</b> tab above to start."
        "</div>",
        unsafe_allow_html=True,
    )


# ─── Results tab ────────────────────────────────────────
def render_d_matrix():
    """D opportunity scatter on Unexpectedness × Impact axes."""
    p = cfg.OUTPUT_DIR / "D_opportunity_scenarios_ja.json"
    if not p.exists():
        st.info("Matrix not available yet — run Step ④ first.")
        return
    try:
        data = read_json(p)
    except Exception as e:
        st.warning(f"Could not load D output: {e}")
        return
    if not data:
        st.info("D output is empty.")
        return

    try:
        import plotly.graph_objects as go
    except ImportError:
        st.warning("plotly not installed — `pip install plotly` to see the matrix.")
        return

    COLORS = {
        "breakthrough": "#7B1FA2",
        "surprising": "#F57C00",
        "incremental": "#1976D2",
        "low_priority": "#9E9E9E",
    }
    LABELS_Q = {
        "breakthrough": "Breakthrough",
        "surprising": "Surprising",
        "incremental": "Incremental",
        "low_priority": "Low priority",
    }

    def _coerce_num(v) -> float:
        # A string would silently turn the plotly axis categorical.
        try:
            return float(v) if v not in (None, "") else 0.0
        except (ValueError, TypeError):
            return 0.0

    fig = go.Figure()
    by_q: dict[str, list] = {}
    for i, s in enumerate(data, 1):
        q = s.get("matrix_quadrant", "low_priority") or "low_priority"
        by_q.setdefault(q, []).append({
            "x": _coerce_num(s.get("impact_score")),
            "y": _coerce_num(s.get("unexpected_score")),
            "name": f"#{i} {(s.get('opportunity_title') or s.get('title') or '')[:50]}",
        })

    for q, pts in by_q.items():
        fig.add_trace(go.Scatter(
            x=[p["x"] for p in pts],
            y=[p["y"] for p in pts],
            mode="markers",
            name=f"{LABELS_Q.get(q, q)} ({len(pts)})",
            text=[p["name"] for p in pts],
            hovertemplate="<b>%{text}</b><br>Impact: %{x}<br>Unexpectedness: %{y}<extra></extra>",
            marker=dict(size=14, color=COLORS.get(q, "#666"), line=dict(color="#fff", width=2)),
        ))

    fig.update_layout(
        title=dict(
            text="<b>Opportunity Matrix</b><br>"
                 "<span style='font-size:11px;color:#6b7280'>"
                 "Unexpectedness × Impact (median-threshold quadrants)</span>",
            x=0.5, xanchor="center", font=dict(size=15),
        ),
        xaxis=dict(title="Impact →", range=[0, 10], gridcolor="#e5e7eb"),
        yaxis=dict(title="Unexpectedness →", range=[0, 10], gridcolor="#e5e7eb"),
        plot_bgcolor="#fff",
        height=520,
        margin=dict(l=60, r=30, t=70, b=60),
        legend=dict(orientation="h", yanchor="bottom", y=-0.22, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_cost_summary():
    cum_path = _cum_cost_file()
    if not cum_path.exists():
        return
    try:
        cost = read_json(cum_path) or {}
    except Exception:
        return

    total = cost.get("total", {}) or {}
    by_step = cost.get("by_step", {}) or {}
    with st.container(border=True):
        st.markdown("#### 💰 Total cost")
        st.caption("Cumulative across all runs.")
        st.markdown(
            f"<div style='font-size:2rem; font-weight:600; color:#10b981; "
            f"line-height:1.2'>${total.get('cost_usd', 0):.2f}</div>",
            unsafe_allow_html=True,
        )

        # Per-step breakdown — only the four client-facing buckets, no phases.
        STEP_LABEL = {
            "A1": "① Expected Scenarios",
            "B":  "② Weak Signals",
            "C":  "③ Unexpected Scenarios",
            "D":  "④ Opportunities",
        }
        rows = []
        for code, lbl in STEP_LABEL.items():
            v = by_step.get(code) or {}
            if (v.get("cost_usd") or 0) > 0:
                rows.append((lbl, v.get("cost_usd", 0)))
        if rows:
            st.markdown("<div style='margin-top:0.75rem'></div>", unsafe_allow_html=True)
            for lbl, c in rows:
                cols = st.columns([3, 1])
                cols[0].markdown(f"<span style='color:#6b7280'>{lbl}</span>", unsafe_allow_html=True)
                cols[1].markdown(
                    f"<div style='text-align:right;font-family:ui-monospace,monospace;"
                    f"color:#374151'>${c:.2f}</div>",
                    unsafe_allow_html=True,
                )


def render_downloads():
    files = [
        ("① Expected Scenarios", "A1_expected_scenarios", "#1976D2"),
        ("② Selected Weak Signals", "B_selected_weak_signals", "#00897B"),
        ("③ Unexpected Scenarios", "C_unexpected_scenarios", "#F57C00"),
        ("④ Opportunity Scenarios", "D_opportunity_scenarios", "#7B1FA2"),
    ]
    has_any = any((cfg.OUTPUT_DIR / f"{base}_ja.json").exists() for _, base, _ in files)
    if not has_any:
        return

    with st.container(border=True):
        st.markdown("#### 📥 Downloads")
        for label, base, color in files:
            ja = cfg.OUTPUT_DIR / f"{base}_ja.json"
            xlsx = cfg.OUTPUT_DIR / f"{base}.xlsx"
            if not ja.exists():
                continue
            count = "?"
            try:
                count = len(read_json(ja))
            except Exception:
                pass

            cols = st.columns([4, 1, 1, 1])
            cols[0].markdown(f"<span style='color:{color};font-weight:600'>{label}</span>", unsafe_allow_html=True)
            cols[1].caption(f"{count} items")
            with cols[2]:
                if xlsx.exists():
                    st.download_button(
                        "Excel",
                        data=file_bytes_for_download(xlsx),
                        file_name=xlsx.name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_xlsx_{base}",
                        use_container_width=True,
                    )
            with cols[3]:
                st.download_button(
                    "JSON",
                    data=file_bytes_for_download(ja),
                    file_name=ja.name,
                    mime="application/json",
                    key=f"dl_json_{base}",
                    use_container_width=True,
                )


def render_pptx():
    """PowerPoint generation. Requires Node.js + generate_pptx.js on the host."""
    with st.container(border=True):
        st.markdown("#### 🎨 PowerPoint Report")
        st.caption("Build a Japanese PowerPoint deck from the current Expected, Unexpected, and Opportunity scenarios.")

        ready = all_steps_complete()
        running = st.session_state.get("running", False)
        if not ready:
            missing = [STEPS[c]["label"] for c in ("A1", "B", "C", "D")
                       if not step_output_exists(STEPS[c]["key"])]
            st.warning(
                f"Run all four steps before generating the PowerPoint — still missing: "
                + ", ".join(missing)
            )
        elif running:
            st.info("A pipeline step is currently running — wait for it to finish before generating the PowerPoint.")

        # Disable while another step is running too: _gen_pptx blocks the main
        # script thread, which would freeze the live progress fragment.
        if st.button("Generate PPT", key="gen_pptx", disabled=(not ready) or running):
            # subprocess.run blocks the main script thread for ~1–2 minutes.
            # Wrap in a spinner so the page doesn't appear frozen.
            with st.spinner("Generating PowerPoint (~1–2 min)... please wait."):
                _gen_pptx()

        status = st.session_state.get("ppt_status", "")
        if not status:
            return

        if status.startswith("Error"):
            st.error(status)
            return
        if not status.startswith("✓"):
            st.info(status)
            return

        st.success(status)

        # Download appears only after a successful generate. JA only — zh PPT
        # is not generated since translation was removed from the pipeline.
        ja_files = sorted(
            cfg.OUTPUT_DIR.glob("*ja*.pptx"),
            key=lambda p: -p.stat().st_mtime,
        )
        for pf in ja_files[:1]:  # most recent ja file
            st.download_button(
                f"📥 Download {pf.name}",
                data=file_bytes_for_download(pf),
                file_name=pf.name,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key=f"dl_pptx_{pf.name}",
            )


def _gen_pptx():
    st.session_state.ppt_status = "Generating..."
    t0 = time.time()
    try:
        subdir = cfg.OUTPUT_DIR.relative_to(cfg.BASE_DIR)
        # Allowlist only what node needs. Passing the parent process's full
        # environment would leak ANTHROPIC_API_KEY / OPENAI_API_KEY / AWS
        # creds etc. into the subprocess; node stack traces could then echo
        # secrets back into the UI on failure.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "NODE_ENV": os.environ.get("NODE_ENV", "production"),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "PPTX_BASE": str(subdir),
            "PPTX_LANGS": "ja",
        }
        r = subprocess.run(
            ["node", "generate_pptx.js"],
            cwd=str(cfg.BASE_DIR),
            env=env,
            capture_output=True, text=True, timeout=180,
        )
        if r.returncode == 0:
            st.session_state.ppt_status = "✓ PPT generated."
        else:
            # Trim node stack traces and append a clear recovery hint so the
            # client knows this isn't something they can fix themselves.
            raw = (r.stderr or r.stdout or "unknown error").strip()
            err = raw.splitlines()[0][:120] if raw else "unknown error"
            st.session_state.ppt_status = (
                f"Error: {err}  ·  Share this with the LivingLab+ team if it persists."
            )
            logger.error(f"generate_pptx.js failed (rc={r.returncode}): {raw[:1000]}")
    except FileNotFoundError:
        st.session_state.ppt_status = (
            "Error: Node.js is not installed on this host. "
            "PowerPoint generation requires running locally."
        )
    except subprocess.TimeoutExpired:
        # Clean up any half-written .pptx the timeout may have left behind so
        # the next download isn't a corrupt file masquerading as a fresh one.
        for pf in cfg.OUTPUT_DIR.glob("*ja*.pptx"):
            try:
                if pf.stat().st_mtime >= t0:
                    pf.unlink()
                    logger.warning(f"_gen_pptx: removed partial {pf.name} after timeout")
            except Exception as e:
                logger.warning(f"_gen_pptx: cleanup partial pptx failed: {e}")
        st.session_state.ppt_status = (
            "Error: PowerPoint generation took longer than expected. "
            "Try again, or contact the LivingLab+ team."
        )
    except Exception as e:
        logger.exception("generate_pptx.js unexpected failure")
        st.session_state.ppt_status = (
            f"Error: {type(e).__name__}: {str(e)[:120]}  ·  "
            "Share this with the LivingLab+ team if it persists."
        )


def render_results():
    st.markdown("### Results")
    st.caption("Reports, charts, and downloads appear here after running the pipeline.")

    files_exist = any(step_output_exists(k) for k in STEP_OUTPUT)
    if not files_exist:
        with st.container(border=True):
            st.markdown("#### Pipeline progress")
            st.markdown(
                "Run the steps in order. Each row checks off as that step completes."
            )
            for code in ("A1", "B", "C", "D"):
                info = STEPS[code]
                done = step_output_exists(info["key"])
                mark = "✓" if done else "○"
                color = "#10b981" if done else "#9ca3af"
                status = "Done" if done else "Not yet run"
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:0.6rem;padding:0.35rem 0'>"
                    f"<span style='color:{color};font-weight:700;width:1rem'>{mark}</span>"
                    f"<span style='color:#1f2937'>{info['label']}</span>"
                    f"<span style='margin-left:auto;color:#9ca3af;font-size:0.85rem'>{status}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            st.markdown(
                "<div style='margin-top:0.75rem;font-size:0.85rem;color:#6b7280'>"
                "→ Start with the <b>① Expected</b> tab above."
                "</div>",
                unsafe_allow_html=True,
            )
        return

    # D matrix at top if present
    if (cfg.OUTPUT_DIR / "D_opportunity_scenarios_ja.json").exists():
        with st.container(border=True):
            st.markdown("#### 🔮 Opportunity Matrix — Unexpectedness × Impact")
            render_d_matrix()

    render_cost_summary()
    render_downloads()
    render_pptx()


# ─── Main ───────────────────────────────────────────────
def setup_logging():
    """Configure logging once. Prefer /tmp/pipeline.log so the app works on
    read-only deployment filesystems (e.g. Streamlit Cloud); fall back to
    BASE_DIR locally; fall back to stdout-only if neither is writable."""
    if logging.getLogger().handlers:
        return
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    for candidate in (Path("/tmp/pipeline.log"), cfg.BASE_DIR / "pipeline.log"):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with open(candidate, "a", encoding="utf-8"):
                pass
            handlers.append(logging.FileHandler(candidate, encoding="utf-8"))
            break
        except (OSError, PermissionError):
            continue
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def main():
    setup_logging()
    init_state()

    # Auth gate (does nothing if APP_USER / APP_PASS aren't set)
    if AUTH_REQUIRED and not st.session_state.get("authenticated"):
        render_login()
        return

    # Auto-mirror + auto-restore sacred caches before anything else runs, so
    # check_prerequisites and the Run buttons reflect a self-healed state.
    sync_sacred_backups()

    # Header — title on the left, sign-out on the right when auth is enabled
    hcol1, hcol2 = st.columns([4, 1])
    with hcol1:
        st.markdown(
            '<h2 style="margin-bottom:0">🔮 AI Scenario Pipeline (JRI x Living Lab+)</h2>'
            '<div style="color:#6b7280;font-size:0.9rem;margin-top:0.1rem">'
            f'Topic: <b>{cfg.TOPIC}</b>'
            '</div>',
            unsafe_allow_html=True,
        )
    with hcol2:
        if AUTH_REQUIRED:
            st.markdown("<div style='margin-top:1.2rem'></div>", unsafe_allow_html=True)
            if st.button("Sign out", key="sign_out", use_container_width=True):
                st.session_state.authenticated = False
                st.rerun()
        else:
            st.markdown(
                "<div style='margin-top:0.5rem; font-size:0.75rem; color:#b45309; "
                "background:#fffbeb; border:1px solid #fde68a; border-radius:6px; "
                "padding:0.4rem 0.6rem; text-align:center'>"
                "⚠ No login set<br>"
                "<span style='font-size:0.7rem'>set APP_USER / APP_PASS</span>"
                "</div>",
                unsafe_allow_html=True,
            )

    # Show API-key warnings only when something is misconfigured, not as a
    # constant green-light — clients don't need to see infra status normally.
    missing_keys = []
    if not getattr(cfg, "ANTHROPIC_API_KEY", ""):
        missing_keys.append("ANTHROPIC_API_KEY (Claude)")
    if not getattr(cfg, "OPENAI_API_KEY", ""):
        missing_keys.append("OPENAI_API_KEY (OpenAI)")
    if missing_keys:
        st.error(
            "Missing API key(s): " + ", ".join(missing_keys)
            + ". Set these in the environment / Streamlit secrets before running."
        )

    st.markdown("<hr style='margin:0.5rem 0 1rem 0;border:none;border-top:1px solid #e5e7eb'>", unsafe_allow_html=True)

    # Compact persistent badge — visible across all tabs while a step runs.
    # The full progress card lives inside each step tab (see render_step_tab).
    header_running_badge()

    def _tab_label(code):
        info = STEPS[code]
        if step_output_exists(info["key"]):
            return f"✓ {info['tab_label']}"
        return info["tab_label"]

    tabs = st.tabs([
        "Setup",
        _tab_label("A1"),
        _tab_label("B"),
        _tab_label("C"),
        _tab_label("D"),
        "Results",
    ])

    with tabs[0]:
        render_setup()

    with tabs[1]:
        render_step_tab(
            "A1",
            description_md=(
                "Analyzes thousands of news articles to identify structural changes that could "
                "reshape industries in the next 10–15 years. Articles are grouped by theme, then "
                "AI writes scenario narratives and scores them on five dimensions: structural depth, "
                "irreversibility, industry fit, topic relevance, and feasibility."
            ),
            note="Article summarization has been pre-processed. Press Run to generate scenarios.",
        )

    with tabs[2]:
        render_step_tab(
            "B",
            description_md=(
                "Selects the most useful weak signals to feed into Unexpected Scenarios. "
                "AI scores each signal on three dimensions (outside the client's area, novelty, "
                "social impact); the system then ranks and removes near-duplicates. Scores are "
                "cached, so adjusting weights or the keep-count only re-ranks the existing "
                "scores — it does not re-run the expensive scoring step."
            ),
        )

    with tabs[3]:
        render_step_tab(
            "C",
            description_md=(
                "Takes the selected weak signals and generates unexpected future scenarios. "
                "Pick how adventurous the output should be via the combine-mode setting:\n\n"
                "- **Single theme** — each scenario built from one thematic cluster. Most focused, least surprising.\n"
                "- **Collide two themes** (default) — pair up two different themes per scenario. Forces cross-domain angles.\n"
                "- **Mix random signals** — any two unrelated signals thrown together. Wildest, least grounded."
            ),
        )

    with tabs[4]:
        render_step_tab(
            "D",
            description_md=(
                "Combines Expected Scenarios (structural trends) with Unexpected Scenarios "
                "(surprising futures) to discover business opportunities. AI pairs scenarios from both "
                "sets, then generates concrete opportunity ideas and scores them on business impact, "
                "unexpectedness, and plausibility."
            ),
        )

    with tabs[5]:
        render_results()


if __name__ == "__main__":
    main()
