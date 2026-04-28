"""
JRI Pipeline V2 — Web UI
"""
import asyncio
import logging
import os
from datetime import datetime

from nicegui import ui, app
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

import config as cfg
from config import UI_PARAMS, apply_overrides

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ─── Auth ───────────────────────────────────────────
AUTH_USERS = {
    os.getenv("APP_USER", "jri"): os.getenv("APP_PASS", "livinglab2026"),
}
UNRESTRICTED = {"/login"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not app.storage.user.get("authenticated", False):
            if request.url.path in UNRESTRICTED or request.url.path.startswith("/_nicegui"):
                return await call_next(request)
            app.storage.user["referrer_path"] = request.url.path
            return RedirectResponse("/login")
        return await call_next(request)


app.add_middleware(AuthMiddleware)


@ui.page("/login")
def login_page():
    ui.add_head_html("""<style>
        body { background: #f7f8fa; }
    </style>""")
    with ui.column().classes("absolute-center items-center gap-4"):
        with ui.column().classes("items-center gap-1 mb-4"):
            ui.label("JRI").classes("text-sm font-bold text-indigo-600 bg-indigo-50 px-3 py-1 rounded")
            ui.label("Living Lab+ Pipeline").classes("text-lg font-semibold text-gray-700")
        with ui.card().classes("w-80 p-6").style("border-radius: 14px; border: 1px solid #ebedf0"):
            username = ui.input("Username").classes("w-full").props("outlined dense")
            password = ui.input("Password", password=True, password_toggle_button=True).classes("w-full").props("outlined dense")
            error_label = ui.label("").classes("text-xs text-red-500")

            async def try_login():
                u = username.value.strip()
                p = password.value
                if u in AUTH_USERS and AUTH_USERS[u] == p:
                    app.storage.user["authenticated"] = True
                    app.storage.user["username"] = u
                    target = app.storage.user.get("referrer_path", "/")
                    ui.navigate.to(target)
                else:
                    error_label.text = "Invalid username or password"

            ui.button("Sign in", icon="login", on_click=try_login).classes("w-full mt-2").props("unelevated no-caps color=indigo")
            password.on("keydown.enter", try_login)

state = {"running": False, "step": "", "logs": [], "last_run": None,
         "last_summary": None, "phase": "", "phase_num": 0, "phase_total": 0,
         "cancel": False, "start_time": None}

LABELS = {
    "run_a1": "Expected Scenarios",
    "run_b": "Weak Signals",
    "run_c": "Unexpected Scenarios",
    "run_d": "Opportunities",
}
ACTION_IMPACT = {
    "run_a1": ("This will generate new expected scenarios.", "Run Opportunities afterward to update."),
    "run_b": ("This will re-rank and re-deduplicate weak signals with the current weights. The expensive AI scoring step is reused from cache.", "Unexpected Scenarios may change after this run."),
    "run_c": ("This will generate new unexpected scenarios.", "Run Opportunities afterward to update."),
    "run_d": ("This will generate new opportunities.", ""),
}
STEPS = {
    "A1": {"icon": "article", "title": "Expected Scenarios",
           "sub": "Identify structural changes from news articles",
           "color": "blue", "section": "A1 Expected"},
    "B":  {"icon": "sensors", "title": "Weak Signals",
           "sub": "Score and select emerging signals",
           "color": "teal", "section": "B Weak Signal"},
    "C":  {"icon": "bolt", "title": "Unexpected Scenarios",
           "sub": "Generate surprising future scenarios from signals",
           "color": "orange", "section": "C Unexpected"},
    "D":  {"icon": "lightbulb", "title": "Opportunities",
           "sub": "Discover business opportunities by combining expected and unexpected scenarios",
           "color": "purple", "section": "D Opportunity"},
}


def _matrix_placeholder(msg):
    with ui.column().classes("w-full items-center py-8 bg-gray-50 rounded-lg"):
        ui.icon("scatter_plot", size="2rem").classes("text-gray-300 mb-2")
        ui.label(msg).classes("text-sm text-gray-500")


def render_d_matrix():
    """Render D opportunities as a scatter plot on Unexpectedness × Impact axes."""
    try:
        from utils.data_io import read_json
        p = cfg.OUTPUT_DIR / "D_opportunity_scenarios_ja.json"
        if not p.exists():
            _matrix_placeholder("Matrix not available yet — run Step D first.")
            return
        data = read_json(p)
        if not data:
            _matrix_placeholder("D output is empty.")
            return

        COLORS = {"breakthrough": "#7B1FA2", "surprising": "#F57C00", "incremental": "#1976D2", "low_priority": "#9E9E9E"}
        points = []
        for i, s in enumerate(data, 1):
            x = s.get("impact_score", 0) or 0
            y = s.get("unexpected_score", 0) or 0
            q = s.get("matrix_quadrant", "")
            title = s.get("opportunity_title") or s.get("opportunity_title_ja") or s.get("scenario_id", "") or ""
            points.append({
                "value": [x, y],
                "name": f"#{i} {title}",
                "label_text": title[:18] + ("…" if len(title) > 18 else ""),
                "itemStyle": {"color": COLORS.get(q, "#666"), "borderColor": "#fff", "borderWidth": 2},
                "q": q,
            })

        # Labels hidden by default — they overlap badly when many points cluster
        # in the same quadrant. Hover the dot to see the full title in the tooltip.
        for p_ in points:
            p_["label"] = {"show": False}
            p_["emphasis"] = {
                "label": {
                    "show": True,
                    "position": "right",
                    "formatter": p_["label_text"],
                    "fontSize": 11,
                    "color": "#333",
                    "distance": 6,
                    "backgroundColor": "rgba(255,255,255,0.95)",
                    "padding": [2, 6],
                    "borderRadius": 4,
                },
            }

        option = {
            "title": {
                "text": "Opportunity Matrix",
                "subtext": "Unexpectedness × Impact (median-threshold quadrants)",
                "left": "center",
                "top": 4,
                "textStyle": {"fontSize": 14, "fontWeight": 600, "color": "#1f2937"},
                "subtextStyle": {"fontSize": 11, "color": "#6b7280"},
            },
            "grid": {"left": 70, "right": 40, "top": 70, "bottom": 70},
            "xAxis": {
                "name": "Impact →",
                "nameLocation": "middle",
                "nameGap": 32,
                "nameTextStyle": {"fontSize": 12, "fontWeight": 500, "color": "#374151"},
                "min": 0,
                "max": 10,
                "splitLine": {"show": True, "lineStyle": {"color": "#e5e7eb"}},
            },
            "yAxis": {
                "name": "Unexpectedness →",
                "nameLocation": "middle",
                "nameGap": 40,
                "nameTextStyle": {"fontSize": 12, "fontWeight": 500, "color": "#374151"},
                "min": 0,
                "max": 10,
                "splitLine": {"show": True, "lineStyle": {"color": "#e5e7eb"}},
            },
            "tooltip": {
                "trigger": "item",
                "backgroundColor": "rgba(255,255,255,0.95)",
                "borderColor": "#e5e7eb",
                "textStyle": {"color": "#1f2937", "fontSize": 12},
                "formatter": "<b>{b}</b><br/><span style='color:#6b7280;font-size:11px'>Impact · Unexpectedness: {c}</span>",
            },
            "series": [{
                "type": "scatter",
                "symbolSize": 18,
                "data": points,
                "emphasis": {"scale": 1.3},
            }],
        }
        ui.echart(option).classes("w-full").style("height: 480px")

        # Legend
        with ui.row().classes("gap-3 flex-wrap mt-1"):
            for q, label, hint in [
                ("breakthrough", "Breakthrough", "High impact × high novelty (priority)"),
                ("surprising", "Surprising", "High novelty × lower impact"),
                ("incremental", "Incremental", "High impact × expected"),
                ("low_priority", "Low priority", "Both low"),
            ]:
                count = sum(1 for s in data if s.get("matrix_quadrant") == q)
                with ui.row().classes("items-center gap-1"):
                    ui.html(f'<span style="display:inline-block;width:10px;height:10px;border-radius:5px;background:{COLORS[q]}"></span>')
                    ui.label(f"{label} ({count})").classes("text-xs text-gray-600")
    except Exception as e:
        logger.warning(f"render_d_matrix failed: {e}")
        _matrix_placeholder(f"Matrix render error: {e}")


def build_summary(step_key):
    try:
        from utils.data_io import read_json
        omap = {
            "run_a1": ("A1_expected_scenarios_ja.json", "scenarios generated", "title", "a1_diversity.json"),
            "run_b": ("B_selected_weak_signals_ja.json", "signals selected", "title", None),
            "run_c": ("C_unexpected_scenarios_ja.json", "scenarios generated", "title", "c_diversity.json"),
            "run_d": ("D_opportunity_scenarios_ja.json", "opportunities found", "opportunity_title", "d_diversity.json"),
        }
        if step_key in omap:
            fn, lbl, tk, div_fn = omap[step_key]
            d = cfg.OUTPUT_DIR if step_key.startswith("run_") else cfg.INTERMEDIATE_DIR
            p = d / fn
            if p.exists():
                data = read_json(p)
                # Preview cap per step: enough to scan but not overwhelm step card.
                # Full list is in Results tab.
                limit = 100 if step_key == "run_b" else 20
                pv = []
                for it in data[:limit]:
                    title = (it.get(tk) or "").strip()
                    if not title:
                        continue
                    entry = {"title": title[:60]}
                    if step_key == "run_a1":
                        # A scenarios are "X shifts from FROM to TO" — showing the
                        # keywords makes the shift readable without opening Excel.
                        frm = (it.get("change_from_keyword") or "").strip()
                        to = (it.get("change_to_keyword") or "").strip()
                        if frm or to:
                            entry["shift"] = f"{frm[:40]} → {to[:40]}"
                    elif step_key == "run_d":
                        a_ids = [a.get("id", "") for a in (it.get("selected_expected") or []) if isinstance(a, dict)]
                        c_ids = [c.get("id", "") for c in (it.get("selected_unexpected") or []) if isinstance(c, dict)]
                        refs = " × ".join([x for x in (" / ".join(a_ids), " / ".join(c_ids)) if x])
                        if refs:
                            entry["refs"] = refs
                    pv.append(entry)
                result = {"count": len(data), "label": lbl, "previews": pv}
                warnings = [
                    ln for ln in state.get("logs", [])
                    if "all dimension weights are 0" in ln
                ]
                if warnings:
                    result["warning"] = (
                        "All dimension weights were 0 — ranking fell back to total_score. "
                        "Set at least one weight > 0 in the settings panel."
                    )
                if div_fn:
                    div_path = cfg.INTERMEDIATE_DIR / div_fn
                    if div_path.exists():
                        try:
                            div = read_json(div_path)
                            result["diversity"] = {
                                "top_topic": div.get("top_topic", ""),
                                "top_industry": div.get("top_industry", ""),
                                "note": div.get("diversity_ja", ""),
                            }
                        except Exception:
                            pass
                return result
    except Exception:
        pass
    return None


def _archive_step_outputs(key):
    """Before a run, move the step's existing outputs into data/output/<subdir>/history/<timestamp>/.

    Cascade: re-running an upstream step also archives downstream outputs AND
    deletes their intermediate caches, so the user is forced to regenerate
    downstream steps against the fresh upstream data. Without this, D can
    reference A/C scenario_ids that no longer exist (the "AA-57" display bug).
    Dependency graph:
        A1 → D        (D reads A1 output)
        B  → C → D    (C reads B output, D reads C output)
    """
    import shutil
    from datetime import datetime
    # Output-file prefixes per run key: upstream first, then every stale downstream.
    prefix_map = {
        "run_a1": [
            "A1_expected_scenarios",
            "D_opportunity_scenarios", "C_used_in_D",
        ],
        "run_b": [
            "B_selected_weak_signals",
            "C_unexpected_scenarios",
            "D_opportunity_scenarios", "C_used_in_D",
        ],
        "run_c": [
            "C_unexpected_scenarios",
            "D_opportunity_scenarios", "C_used_in_D",
        ],
        "run_d": ["D_opportunity_scenarios", "C_used_in_D"],
    }
    # Intermediate caches to delete (not archive — no point preserving stale pairs/checkpoints).
    # Keyed by which downstream step's cache should go when the run key triggers.
    intermediate_to_delete = {
        "run_a1": ["d_phase1_pairs.json", "d_phase2_scenarios.json", "d_phase2_checkpoint.json"],
        "run_b":  [
            "c_phase1_clusters.json", "c_phase2_scenarios.json", "c_phase2_checkpoint.json",
            "d_phase1_pairs.json", "d_phase2_scenarios.json", "d_phase2_checkpoint.json",
        ],
        "run_c":  ["d_phase1_pairs.json", "d_phase2_scenarios.json", "d_phase2_checkpoint.json"],
        "run_d":  [],
    }
    prefixes = prefix_map.get(key)
    if not prefixes:
        return
    out_dir = cfg.OUTPUT_DIR
    matches = [p for pf in prefixes for p in out_dir.glob(f"{pf}*") if p.is_file()]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if matches:
        archive_dir = out_dir / "history" / f"{ts}_{key}"
        archive_dir.mkdir(parents=True, exist_ok=True)
        for p in matches:
            try:
                shutil.move(str(p), str(archive_dir / p.name))
            except Exception as e:
                logger.warning(f"archive {p.name} failed: {e}")
        logger.info(f"Archived {len(matches)} file(s) to {archive_dir.relative_to(cfg.BASE_DIR)}")
    deleted = 0
    for fn in intermediate_to_delete.get(key, []):
        p = cfg.INTERMEDIATE_DIR / fn
        if p.exists():
            try:
                p.unlink()
                deleted += 1
            except Exception as e:
                logger.warning(f"delete {fn} failed: {e}")
    if deleted:
        logger.info(f"Invalidated {deleted} downstream intermediate cache file(s)")


class LogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        msg = msg.replace(str(cfg.BASE_DIR) + "/", "").replace(str(cfg.BASE_DIR), "")
        state["logs"].append(msg)
        if len(state["logs"]) > 300:
            state["logs"] = state["logs"][-300:]


_LAST_RUN_PARAMS_FILE = lambda: cfg.INTERMEDIATE_DIR / "_last_run_params.json"

# UI param keys whose change invalidates each step's cache (rough heuristic for
# the "settings changed since last run?" detection in the Run dialog).
_STEP_PARAM_PREFIXES = {
    "run_a1": ("A1_", "TOPIC", "TIMEFRAME", "INDUSTRIES"),
    "run_b":  ("B_",  "TOPIC", "TIMEFRAME", "INDUSTRIES"),
    "run_c":  ("C_",  "TOPIC", "TIMEFRAME", "INDUSTRIES"),
    "run_d":  ("D_",  "TOPIC", "TIMEFRAME", "INDUSTRIES"),
}


def _load_last_run_params():
    p = _LAST_RUN_PARAMS_FILE()
    if not p.exists():
        return {}
    try:
        from utils.data_io import read_json
        return read_json(p) or {}
    except Exception:
        return {}


def _save_last_run_params(key, params):
    from utils.data_io import save_json
    all_runs = _load_last_run_params()
    all_runs[key] = {k: v for k, v in params.items()}
    try:
        save_json(all_runs, _LAST_RUN_PARAMS_FILE())
    except Exception as e:
        logger.warning(f"_save_last_run_params: {e}")


def _settings_changed_since_last_run(key, current_params):
    """True if any param relevant to `key` differs from the last successful run.
    True also if there's no record (first run). False means cache will likely be reused."""
    last = _load_last_run_params().get(key)
    if not last:
        return True
    prefixes = _STEP_PARAM_PREFIXES.get(key, ())
    relevant = lambda k: any(k == pre or k.startswith(pre) for pre in prefixes)
    keys_to_check = {k for k in current_params if relevant(k)} | {k for k in last if relevant(k)}
    for k in keys_to_check:
        if current_params.get(k) != last.get(k):
            return True
    return False


def _clear_regen_cache(key):
    """Force-regenerate cache cleanup. Wipes the step's intermediate files
    so generation re-runs from scratch, but preserves the most expensive
    LLM caches: A1 Phase 1 article summaries and B Phase 1 signal scoring."""
    inter = cfg.INTERMEDIATE_DIR
    targets_per_step = {
        "run_a1": [
            "a1_phase2_themes.json",
            "a1_phase3_scenarios.json",
            "a1_phase3_checkpoint.json",
            "a1_phase4_ranked.json",
            "a1_diversity.json",
        ],
        "run_b": [
            "b_phase2_top3000_candidates.json",
            "b_phase3_dedup_selected.json",
            "b_phase3_dedup_selected.meta.json",
            "b_phase3_dedup_summary.json",
        ],
        "run_c": [
            "c_phase1_clusters.json",
            "c_phase2_scenarios.json",
            "c_phase2_checkpoint.json",
            "c_diversity.json",
        ],
        "run_d": [
            "d_phase1_pairs.json",
            "d_phase2_scenarios.json",
            "d_phase2_checkpoint.json",
        ],
    }
    removed = []
    for name in targets_per_step.get(key, []):
        p = inter / name
        if p.exists():
            try:
                p.unlink()
                removed.append(name)
            except Exception as e:
                logger.warning(f"_clear_regen_cache: failed to remove {p}: {e}")
    if removed:
        logger.info(f"{key}: cleared {len(removed)} cache files for fresh regeneration: {removed}")
    return removed


def _check_prerequisites(key):
    """Return (ok, error_message). Guards that upstream outputs exist before running a step."""
    from utils.data_io import read_json
    if key == "run_d":
        a1 = cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json"
        c = cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json"
        missing = [p.name for p in (a1, c) if not p.exists()]
        if missing:
            return False, f"Run A1 and C first — missing: {', '.join(missing)}"
        try:
            if not read_json(a1):
                return False, "A1 output is empty — re-run Step A1."
            if not read_json(c):
                return False, "C output is empty — re-run Step C."
        except Exception as e:
            return False, f"Could not read A1/C outputs: {e}"
    elif key == "run_c":
        b_cache = cfg.INTERMEDIATE_DIR / "b_phase3_dedup_selected.json"
        if not b_cache.exists():
            return False, "Step C needs Step B output — run B first."
        b_meta = cfg.INTERMEDIATE_DIR / "b_phase3_dedup_selected.meta.json"
        if not b_meta.exists():
            return False, "Step C needs Step B metadata — re-run Step B."
        try:
            meta = read_json(b_meta)
            if str(meta.get("topic", "") or "") != str(cfg.TOPIC or ""):
                return False, "Step C needs Step B re-run for current Research Topic."
            if "timeframe" in meta and str(meta.get("timeframe", "") or "") != str(cfg.TIMEFRAME or ""):
                return False, "Step C needs Step B re-run for current Time Horizon."
            if "industries" in meta:
                meta_inds = [str(x) for x in (meta.get("industries") or [])]
                curr_inds = [str(x) for x in ((getattr(cfg, "CLIENT_PROFILE", {}) or {}).get("industries") or [])]
                if meta_inds != curr_inds:
                    return False, "Step C needs Step B re-run for current Target Industries."
        except Exception as e:
            return False, f"Could not read Step B metadata: {e}"
    return True, None


async def run_step(key, ov):
    if state["running"]:
        ui.notify("Already running.", type="warning"); return
    apply_overrides(ov)
    ok, err = _check_prerequisites(key)
    if not ok:
        ui.notify(err, type="warning", timeout=5000); return
    # Reset cost trackers so cost_report.json reflects only this run's cost.
    try:
        from utils.llm_client import get_client as _get_claude
        from utils.openai_client import get_openai_client as _get_oai
        _get_claude().tracker.reset()
        _get_oai().reset_usage()
    except Exception as _e:
        logger.warning(f"cost-tracker reset failed: {_e}")
    import time as _time
    state.update(running=True, step=key, logs=[], last_summary=None,
                 phase="Starting...", phase_num=0, phase_total=0,
                 cancel=False, start_time=_time.time())
    _archive_step_outputs(key)

    def _run():
        def _p(name, n, t):
            state.update(phase=name, phase_num=n, phase_total=t)
        def _check_cancel():
            if state.get("cancel"):
                raise InterruptedError("Cancelled by user")
        try:
            if key == "run_a1":
                from steps.step_a1 import phase2_cluster, phase3_generate, phase4_rank
                _p("Clustering articles...", 1, 3); themes = phase2_cluster()
                _p("Generating scenarios...", 2, 3); scenarios = phase3_generate(themes)
                _p("Scoring, filtering, review...", 3, 3); phase4_rank(scenarios)
            elif key == "run_b":
                from steps.step_b import score_signals, diversity_dedup
                _p("Scoring signals...", 1, 2); score_signals()
                _p("Ranking & deduplicating signals...", 2, 2); diversity_dedup()
            elif key == "run_c":
                from steps.step_c import phase1_cluster, phase1_cluster_pair, phase1_signal_pair, phase2_generate, phase3_rank
                _p("Grouping signals...", 1, 3)
                if cfg.C_MODE == "cluster_pair":
                    cl = phase1_cluster_pair()
                elif cfg.C_MODE == "signal_pair":
                    cl = phase1_signal_pair()
                else:
                    cl = phase1_cluster()
                _p("Generating scenarios...", 2, 3); sc = phase2_generate(cl)
                _p("Scoring & ranking...", 3, 3); phase3_rank(sc)
            elif key == "run_d":
                from steps.step_d import phase1_random_pairs, phase2_generate, phase3_rank
                from utils.data_io import read_json
                exp = read_json(cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json")
                unexp = read_json(cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json")
                _p("Pairing scenarios...", 1, 3); pairs = phase1_random_pairs(exp, unexp)
                _p("Generating opportunities...", 2, 3); sc = phase2_generate(pairs, exp, unexp)
                _p("Scoring, filtering, classifying...", 3, 3); phase3_rank(sc)
            from run_pipeline import save_cost_report
            save_cost_report()
            state["last_summary"] = build_summary(key)
            _save_last_run_params(key, ov)
        except InterruptedError:
            state["last_summary"] = {"error": "Cancelled by user"}
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            state["last_summary"] = {"error": str(e)}
        finally:
            state.update(running=False, last_run=datetime.now().strftime("%H:%M"))
    await asyncio.get_event_loop().run_in_executor(None, _run)


def render_params(section, P, exclude=None):
    exclude = set(exclude or ())
    items = [(k, v) for k, v in UI_PARAMS.items() if v["section"] == section and k not in exclude]
    main = [(k, v) for k, v in items if v.get("priority") == "main"]
    adv = [(k, v) for k, v in items if v.get("priority") == "advanced"]

    toast_state = {"ts": 0.0, "count": 0}

    def _ping(k, v):
        import time as _t
        P[k] = v
        toast_state["count"] += 1
        now = _t.time()
        # Throttle: one toast per 2 seconds, summarizing batched changes
        if now - toast_state["ts"] > 2.0:
            n = toast_state["count"]
            ui.notify(
                f"{n} setting{'s' if n != 1 else ''} updated",
                type="positive", position="bottom-right", timeout=1200,
            )
            toast_state["ts"] = now
            toast_state["count"] = 0

    # Weight-row color coding — ties scoring weights visually to their step tab.
    WEIGHT_COLORS = {"A1_": "#1976D2", "B_": "#00897B", "C_": "#F57C00", "D_": "#7B1FA2"}

    def _weight_color(key):
        if "_WEIGHT_" not in key:
            return None
        for prefix, c in WEIGHT_COLORS.items():
            if key.startswith(prefix):
                return c
        return None

    def _f(k, s):
        d = s["default"]; P.setdefault(k, d); h = s.get("hint", "")
        wc = _weight_color(k)
        if s["type"] == "number":
            mx = s.get("max")
            mn = s.get("min", 0)
            with ui.row().classes("w-full items-center justify-between py-1"):
                with ui.row().classes("items-center gap-2"):
                    if wc:
                        ui.html(f'<span style="display:inline-block;width:8px;height:8px;border-radius:4px;background:{wc};flex-shrink:0"></span>')
                    ui.label(s["label"]).classes("text-sm text-gray-700")
                with ui.row().classes("items-center gap-2"):
                    n = ui.number(value=d, min=mn, max=mx if mx is not None else 100).classes("w-24").props("dense outlined")
                    if wc:
                        n.style(f"border-left: 3px solid {wc}; padding-left: 4px")
                    n.on_value_change(lambda e, k=k: _ping(k, e.value))
                    if mx is not None:
                        ui.label(f"max {mx}").classes("text-xs text-gray-400 font-mono")
            if h: ui.label(h).classes("text-xs text-gray-500 -mt-1 leading-snug")
        elif s["type"] == "bool":
            with ui.row().classes("w-full items-center justify-between py-1"):
                ui.label(s["label"]).classes("text-sm text-gray-700")
                sw = ui.switch(value=d).props("dense")
                sw.on_value_change(lambda e, k=k: _ping(k, e.value))
            if h: ui.label(h).classes("text-xs text-gray-500 leading-snug")
        elif s["type"] == "select":
            with ui.row().classes("w-full items-center justify-between py-1"):
                ui.label(s["label"]).classes("text-sm text-gray-700")
                sl = ui.select(s["options"], value=d).classes("w-64").props("dense outlined")
                sl.on_value_change(lambda e, k=k: _ping(k, e.value))
            if h: ui.label(h).classes("text-xs text-gray-500 -mt-1 leading-snug")
        elif s["type"] == "text":
            t = ui.input(label=s["label"], value=str(d)).classes("w-full").props("dense outlined")
            t.on_value_change(lambda e, k=k: _ping(k, e.value))
            if h: ui.label(h).classes("text-xs text-gray-500 leading-snug")

    for k, s in main:
        _f(k, s)
    if adv:
        active_count = sum(1 for k, s in adv if P.get(k, s["default"]) > 0 and s["type"] == "number")
        ui.separator().classes("my-2 opacity-30")
        with ui.expansion(
            f"Scoring Weights ({active_count} active)",
            icon="tune",
            value=True,
        ).classes("w-full").props("dense"):
            ui.label("All weights equal (e.g. all 1, or all 10) gives the same ranking. Change the ratios between weights to shift the priority.").classes("text-xs text-gray-500 mb-2 leading-snug")
            for k, s in adv:
                _f(k, s)
            def _reset():
                for k, s in adv: P[k] = s["default"]
                ui.notify("Reset to defaults", type="info")
            ui.button("Reset to defaults", icon="restart_alt", on_click=_reset).props("flat no-caps size=sm color=grey").classes("mt-2")


def _version_info():
    """Read git commit + date; fall back to static."""
    try:
        import subprocess
        r = subprocess.run(["git", "log", "-1", "--format=%h %cs"],
                           cwd=str(cfg.BASE_DIR), capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and r.stdout.strip():
            commit, date = r.stdout.strip().split(" ", 1)
            return f"v1.0 · build {commit} · {date}"
    except Exception:
        pass
    return "v1.0"


# ─── Page ───────────────────────────────────────────

@ui.page("/")
def page():
    ui.add_head_html("""<style>
        body { background: #f7f8fa; }
        .card-s { border-radius: 14px !important; border: 1px solid #ebedf0 !important; box-shadow: none !important; }
        .card-s:hover { border-color: #dcdfe3 !important; }
        .q-tab { text-transform: none !important; font-size: 13px !important; }
        .q-btn { text-transform: none !important; }
        .q-tab-panels { overflow: visible !important; }
        .q-panel.scroll { overflow: visible !important; }
        /* Tab accent colors — active with background */
        .q-tab[name="a1"].q-tab--active { color: #1976D2 !important; background: #E3F2FD !important; border-radius: 8px 8px 0 0; }
        .q-tab[name="a1"] .q-tab__indicator { background: #1976D2 !important; height: 3px !important; }
        .q-tab[name="b"].q-tab--active { color: #00897B !important; background: #E0F2F1 !important; border-radius: 8px 8px 0 0; }
        .q-tab[name="b"] .q-tab__indicator { background: #00897B !important; height: 3px !important; }
        .q-tab[name="c"].q-tab--active { color: #F57C00 !important; background: #FFF3E0 !important; border-radius: 8px 8px 0 0; }
        .q-tab[name="c"] .q-tab__indicator { background: #F57C00 !important; height: 3px !important; }
        .q-tab[name="d"].q-tab--active { color: #7B1FA2 !important; background: #F3E5F5 !important; border-radius: 8px 8px 0 0; }
        .q-tab[name="d"] .q-tab__indicator { background: #7B1FA2 !important; height: 3px !important; }
        /* Tab colors — inactive (muted) */
        .q-tab[name="a1"]:not(.q-tab--active) { color: #64B5F6 !important; }
        .q-tab[name="b"]:not(.q-tab--active) { color: #4DB6AC !important; }
        .q-tab[name="c"]:not(.q-tab--active) { color: #FFB74D !important; }
        .q-tab[name="d"]:not(.q-tab--active) { color: #BA68C8 !important; }
        /* Arrow separators between step tabs */
        .q-tab[name="a1"]::after,
        .q-tab[name="b"]::after,
        .q-tab[name="c"]::after {
            content: "→";
            position: absolute;
            right: -12px;
            top: 50%;
            transform: translateY(-50%);
            color: #ccc;
            font-size: 14px;
            pointer-events: none;
            z-index: 1;
        }
        .progress-card { background: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; padding: 16px; }
        .result-ok { background: #f0fdf4; border: 1px solid #d1fae5; border-radius: 12px; padding: 16px; }
        .result-err { background: #fef2f2; border: 1px solid #fee2e2; border-radius: 12px; padding: 16px; }
    </style>""")

    P = {}
    ui_refs = {}

    # Header — clean, no debug info (#1)
    with ui.column().classes("w-full gap-0"):
        with ui.row().classes("w-full bg-white border-b border-gray-100 px-6 py-2.5 items-center justify-between"):
            with ui.row().classes("items-center gap-2"):
                ui.label("JRI").classes("text-xs font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded")
                ui.label("Living Lab+ Pipeline").classes("text-sm font-semibold text-gray-700")
            with ui.row().classes("items-center gap-3"):
                ui_refs["indicator"] = ui.spinner("dots", size="xs", color="amber")
                ui_refs["indicator"].visible = False
                ui_refs["status"] = ui.label("").classes("text-xs font-medium text-gray-500")
                ui.separator().props("vertical").classes("h-4")
                def logout():
                    app.storage.user.clear()
                    ui.navigate.to("/login")
                ui.button("Logout", icon="logout", on_click=logout).props("flat no-caps size=xs color=grey")
        ui_refs["pbar"] = ui.linear_progress(show_value=False).classes("w-full").props("indeterminate color=amber size=2px")
        ui_refs["pbar"].visible = False

    # Global header tick — single source of truth for status/indicator/pbar
    _hdr = {"running": None}
    def _header_tick():
        running = state["running"]
        if running == _hdr["running"]:
            return
        _hdr["running"] = running
        if running:
            step_name = LABELS.get(state.get("step", ""), state.get("step", ""))
            ui_refs["status"].text = f"Running {step_name}..."
            ui_refs["status"].classes(replace="text-amber-600 text-xs font-medium")
            ui_refs["indicator"].visible = True
            ui_refs["pbar"].visible = True
        else:
            ui_refs["status"].text = ""
            ui_refs["indicator"].visible = False
            ui_refs["pbar"].visible = False
    ui.timer(0.5, _header_tick)

    # Tabs — no ✓ marks (#4)
    with ui.tabs().classes("w-full bg-white border-b border-gray-100 px-4").props(
        "active-color=indigo indicator-color=indigo dense no-caps align=left"
    ) as tabs:
        t_setup = ui.tab("setup", label="Setup", icon="settings")
        t_a1 = ui.tab("a1", label="① Expected Scenarios", icon="article")
        t_b = ui.tab("b", label="② Weak Signals", icon="sensors")
        t_c = ui.tab("c", label="③ Unexpected Scenarios", icon="bolt")
        t_d = ui.tab("d", label="④ Opportunities", icon="lightbulb")
        t_res = ui.tab("res", label="Results", icon="download")

    # Scroll to top on tab change (#11 from prev audit)
    def _on_tab_change():
        ui.run_javascript('window.scrollTo({top: 0}); document.querySelector(".q-tab-panels")&&(document.querySelector(".q-tab-panels").scrollTop=0)')
        # Rebuild Results content when entering Results tab so counts reflect
        # the latest run, not the page-load snapshot.
        try:
            if tabs.value == "res" and state.get("_rebuild_results"):
                state["_rebuild_results"]()
        except Exception:
            pass

    tabs.on_value_change(_on_tab_change)

    with ui.tab_panels(tabs, value=t_setup, animated=False).classes("w-full flex-grow bg-transparent"):

        TAB_MAP = {"A1": "a1", "B": "b", "C": "c", "D": "d"}

        # ═══ SETUP ═══
        with ui.tab_panel(t_setup):
          with ui.column().classes("w-full"):
            with ui.column().classes("w-full max-w-3xl mx-auto py-4 gap-4"):
                ui.label("Setup").classes("text-lg font-semibold text-gray-800")
                ui.label("Configure your analysis settings before running the pipeline.").classes("text-sm text-gray-500 -mt-2")

                # Research Settings — FIRST (most important)
                with ui.card().classes("w-full card-s p-5"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("public", size="sm").classes("text-indigo-500")
                        ui.label("Research Settings").classes("font-semibold text-gray-700")
                    ui.label("These settings affect all steps. Adjust before running.").classes("text-xs text-gray-500 mb-2")
                    render_params("Global", P, exclude=["TRANSLATE_ENABLED"])

                # Data — clean names with counts (#6)
                with ui.card().classes("w-full card-s p-5"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("description", size="sm").classes("text-teal-500")
                        ui.label("Data").classes("font-semibold text-gray-700")
                    ui.label("Pre-loaded datasets for this analysis:").classes("text-xs text-gray-500 mb-2")
                    def _count_rows(path):
                        try:
                            import pandas as pd
                            if path.suffix == ".xlsx":
                                return len(pd.read_excel(path))
                        except Exception:
                            pass
                        return None
                    # Counts shown match the customer-facing deliverable PPT.
                    # A1: 6,135 valid public-report articles (curated subset of the
                    # raw Excel; the file we receive may have additional rows the
                    # customer filtered out before delivery).
                    DISPLAY_COUNTS = {
                        "News articles": 6135,
                        "Weak signals": 9004,
                    }
                    for f, label in [(cfg.A1_INPUT_FILE, "News articles"), (cfg.B_INPUT_FILE, "Weak signals")]:
                        count = DISPLAY_COUNTS.get(label) or _count_rows(f)
                        desc = f"{label} — {count:,} items" if count else label
                        with ui.row().classes("items-center gap-2 py-1"):
                            ui.icon("check_circle", size="xs").classes("text-teal-400")
                            ui.label(desc).classes("text-sm text-gray-600")

        # ═══ STEP TABS ═══
        def step_tab(panel, code, run_key, note=None, extra=None):
            info = STEPS[code]
            color = info.get("color", "indigo")
            section = info.get("section", "")
            with ui.tab_panel(panel):
                with ui.column().classes("w-full"):
                  with ui.column().classes("w-full max-w-5xl mx-auto py-4 gap-4"):
                    # Header with step color
                    with ui.row().classes("w-full items-center gap-3"):
                        ui.icon(info["icon"], size="sm").classes(f"text-{color}-500")
                        with ui.column().classes("gap-0"):
                            ui.label(info["title"]).classes("text-lg font-semibold text-gray-800")
                            ui.label(info["sub"]).classes("text-xs text-gray-500")

                    if note:
                        with ui.row().classes(f"bg-{color}-50 rounded-lg px-3 py-2 items-center gap-2"):
                            ui.icon("info", size="xs").classes(f"text-{color}-400")
                            ui.label(note).classes(f"text-xs text-{color}-700")

                    if extra:
                        extra()

                    # Settings — distinct card
                    with ui.card().classes("w-full card-s p-5").style("border-left: 3px solid #e0e0e0"):
                        with ui.row().classes("items-center gap-2 mb-3"):
                            ui.icon("tune", size="sm").classes(f"text-{color}-400")
                            ui.label("Settings").classes("font-semibold text-gray-700")
                        render_params(section, P)

                    # Run + progress area
                    status_box = ui.column().classes("w-full")

                    async def _click(k=run_key, c=color):
                        if state["running"]:
                            ui.notify("Already running. Please wait for the current step to finish.", type="warning"); return
                        run_btn.disable()
                        rep, down = ACTION_IMPACT.get(k, ("", ""))
                        with ui.dialog() as dlg, ui.card().classes("p-5 max-w-sm"):
                            ui.label(f"Run {info['title']}").classes("text-base font-semibold mb-2")
                            if rep:
                                with ui.row().classes("items-start gap-2"):
                                    ui.icon("info", size="xs").classes(f"text-{c}-400 mt-0.5")
                                    with ui.column().classes("gap-0"):
                                        ui.label(rep).classes("text-xs text-gray-600")
                                        if down:
                                            ui.label(down).classes("text-xs text-gray-500 mt-1")
                            settings_changed = _settings_changed_since_last_run(k, P)
                            regen_switch = None
                            if settings_changed:
                                with ui.row().classes("mt-3 p-3 bg-amber-50 rounded items-start gap-2"):
                                    ui.icon("info", size="sm").classes("text-amber-500 mt-0.5")
                                    ui.label(
                                        "Your settings have changed since the last run. The system will update the results based on the new settings."
                                    ).classes("text-xs text-amber-800 leading-snug flex-grow")
                            else:
                                with ui.column().classes("mt-3 p-3 bg-gray-50 rounded gap-1"):
                                    regen_switch = ui.checkbox(
                                        "Generate new results (don't reuse last run)",
                                        value=False,
                                    ).props("dense")
                                    ui.label(
                                        "Your settings haven't changed, so by default the system will reuse the previous output. "
                                        "Turn this on to force the AI to produce fresh results."
                                    ).classes("text-xs text-gray-500 leading-snug")
                            with ui.row().classes("mt-4 gap-2 justify-end"):
                                def _cancel(d=dlg):
                                    d.close()
                                    run_btn.enable()
                                ui.button("Cancel", on_click=_cancel).props("flat no-caps size=sm")
                                async def _confirmed(d=dlg, k=k, sw=regen_switch):
                                    regen = bool(sw.value) if sw is not None else False
                                    d.close()
                                    run_btn.enable()
                                    if regen:
                                        _clear_regen_cache(k)
                                    await run_step(k, P)
                                ui.button("Run", icon="play_arrow",
                                    on_click=_confirmed
                                ).props(f"unelevated no-caps size=sm color={c}")
                        dlg.open()

                    with ui.column().classes("w-full gap-1"):
                        run_btn = ui.button("Run", icon="play_arrow", on_click=_click).props(f"color={color} size=md").classes("w-full")

                    # No execution log (#7) — just hidden log for tick to push to
                    la = ui.log(max_lines=80).classes("hidden")

                    # Tick — progress display
                    # Track: ("running", phase_num, phase) | ("done", last_run) | ("idle",)
                    _shown = {"v": ("idle",)}

                    def tick(a=la, sb=status_box, btn=run_btn):
                        try:
                            for l in state["logs"]: a.push(l)
                            state["logs"] = []

                            import time as _t
                            running = state["running"]
                            last_run = state.get("last_run")

                            # Disable Run button while any step is running, re-enable when idle
                            try:
                                if running and btn.enabled:
                                    btn.disable()
                                elif not running and not btn.enabled:
                                    btn.enable()
                            except Exception:
                                pass

                            if running:
                                ph = state.get("phase", "")
                                pn = state.get("phase_num", 0)
                                pt = state.get("phase_total", 0)
                                target = ("running", pn, ph)
                                if _shown["v"] != target:
                                    _shown["v"] = target
                                    sb.clear()
                                    with sb:
                                        with ui.card().classes(f"w-full bg-{color}-50 border border-{color}-200 p-4").style("border-radius:10px"):
                                            with ui.row().classes("items-center gap-3"):
                                                ui.spinner("dots", size="sm", color=color)
                                                ui.label("Running...").classes(f"text-sm font-semibold text-{color}-800")
                                            ui.label(ph or "Starting...").classes(f"text-xs text-{color}-600 mt-2")
                                            if pt > 0:
                                                ui.linear_progress(value=pn/pt, show_value=False).classes("w-full mt-1").props(f"color={color} rounded size=8px")
                                            with ui.row().classes("mt-2 justify-end"):
                                                def _cancel():
                                                    state["cancel"] = True
                                                    ui.notify("Cancelling after current phase...", type="warning")
                                                ui.button("Cancel", icon="stop", on_click=_cancel).props("flat no-caps size=xs color=grey")

                            elif last_run:
                                target = ("done", last_run, state.get("step"))
                                if _shown["v"] != target:
                                    _shown["v"] = target
                                    sb.clear()
                                    s = state.get("last_summary")
                                    if s and state.get("step") == run_key:
                                        with sb:
                                            if "error" in s:
                                                err_full = s.get("error", "") or ""
                                                err_short = err_full[:200] + ("…" if len(err_full) > 200 else "")
                                                with ui.column().classes("result-err gap-1 w-full"):
                                                    with ui.row().classes("items-center gap-2"):
                                                        ui.icon("error", size="sm").classes("text-red-500")
                                                        ui.label(f"Error: {err_short}").classes("text-sm text-red-600")
                                                    if len(err_full) > 200:
                                                        with ui.expansion("Show full error", icon="code").classes("text-xs").props("dense"):
                                                            ui.code(err_full).classes("text-xs")
                                            elif "count" in s:
                                                with ui.column().classes("result-ok gap-1 w-full"):
                                                    with ui.row().classes("items-center gap-2"):
                                                        ui.icon("check_circle", size="sm").classes("text-green-500")
                                                        ui.label(f"Done — {s['count']} {s['label']} (at {last_run})").classes("text-sm font-semibold text-green-700")
                                                    if s.get("warning"):
                                                        with ui.row().classes("items-center gap-2 p-2 rounded bg-red-50 border border-red-200"):
                                                            ui.icon("warning", size="xs").classes("text-red-600")
                                                            ui.label(s["warning"]).classes("text-xs text-red-700")
                                                    previews_list = s.get("previews", [])
                                                    if previews_list:
                                                        with ui.expansion(
                                                            f"Preview titles ({len(previews_list)})",
                                                            icon="list",
                                                        ).classes("w-full").props("dense"):
                                                            for idx, pv in enumerate(previews_list, 1):
                                                                if isinstance(pv, dict):
                                                                    with ui.column().classes("gap-0 ml-5 py-1 w-full"):
                                                                        ui.label(f"{idx}. {pv.get('title', '')}").classes("text-xs text-gray-700 leading-snug")
                                                                        if pv.get("shift"):
                                                                            ui.label(pv["shift"]).classes("text-[11px] text-gray-500 ml-4 leading-snug")
                                                                        if pv.get("refs"):
                                                                            ui.label(f"↳ {pv['refs']}").classes("text-[11px] text-gray-500 ml-4 leading-snug")
                                                                else:
                                                                    ui.label(f"{idx}. {pv}").classes("text-xs text-gray-600 ml-5 leading-snug")
                                                    if run_key == "run_d":
                                                        ui.label("→ View the Opportunity Matrix in the Results tab.").classes("text-xs text-gray-500 ml-5 italic")
                            else:
                                if _shown["v"] != ("idle",):
                                    _shown["v"] = ("idle",)
                                    sb.clear()
                        except Exception as e:
                            logger.error(f"tick error: {e}", exc_info=True)
                    ui.timer(1.0, tick)

                    # Navigation — consistent full names (#16)
                    prev_map = {"A1": ("setup", "Setup"), "B": ("a1", "Expected Scenarios"),
                                "C": ("b", "Weak Signals"), "D": ("c", "Unexpected Scenarios")}
                    next_map = {"A1": ("b", "Weak Signals"), "B": ("c", "Unexpected Scenarios"),
                                "C": ("d", "Opportunities"), "D": ("res", "Results")}
                    with ui.row().classes("w-full justify-between mt-2"):
                        if code in prev_map:
                            pk, pl = prev_map[code]
                            ui.button(f"← {pl}", on_click=lambda t=pk: tabs.set_value(t)).props("flat no-caps size=sm color=grey")
                        else:
                            ui.label("")
                        if code in next_map:
                            nk, nl = next_map[code]
                            ui.button(f"{nl} →", on_click=lambda t=nk: tabs.set_value(t)).props("flat no-caps size=sm color=indigo")

        # A1
        def a1_desc():
            with ui.expansion("What this step does", icon="info", value=True).classes("w-full text-sm text-gray-500").props("dense"):
                ui.label(
                    "Analyzes thousands of news articles to identify structural changes that could reshape industries "
                    "in the next 10-15 years. Articles are grouped by theme, then AI writes scenario narratives "
                    "and scores them on five dimensions: structural depth, irreversibility, industry fit, "
                    "topic relevance, and feasibility."
                ).classes("text-sm text-gray-500 leading-relaxed")
        step_tab(t_a1, "A1", "run_a1",
            "Article summarization has been pre-processed. Press Run to generate scenarios.",
            extra=a1_desc)

        # B
        def b_extra():
            with ui.expansion("What this step does", icon="info", value=False).classes("w-full text-sm text-gray-500").props("dense"):
                ui.label(
                    "Selects the most useful weak signals to feed into Unexpected Scenarios. "
                    "AI scores each signal on three dimensions (outside the client's area, novelty, social impact); "
                    "the system then ranks and removes near-duplicates. Scores are cached, so adjusting weights or "
                    "the keep-count only re-ranks the existing scores — it does not re-run the expensive scoring step."
                ).classes("text-sm text-gray-500 leading-relaxed")

        step_tab(
            t_b,
            "B",
            "run_b",
            extra=b_extra,
        )

        # C
        def c_extra():
            with ui.expansion("What this step does", icon="info", value=True).classes("w-full text-sm text-gray-500").props("dense"):
                ui.label(
                    "Takes the selected weak signals and generates unexpected future scenarios. "
                    "Pick how adventurous the output should be via the combine-mode setting."
                ).classes("text-sm text-gray-600 leading-relaxed")
                ui.separator().classes("my-2 opacity-30")
                with ui.column().classes("gap-1"):
                    ui.label("How signals are combined").classes("text-sm font-medium text-gray-700")
                    ui.label("• Single theme — each scenario built from one thematic cluster. Most focused, least surprising.").classes("text-xs text-gray-500")
                    ui.label("• Collide two themes (default) — pair up two different themes per scenario. Forces cross-domain angles.").classes("text-xs text-gray-500")
                    ui.label("• Mix random signals — any two unrelated signals thrown together. Wildest, least grounded.").classes("text-xs text-gray-500")

        step_tab(t_c, "C", "run_c", extra=c_extra)

        # D
        def d_extra():
            with ui.expansion("What this step does", icon="info", value=True).classes("w-full text-sm text-gray-500").props("dense"):
                ui.label(
                    "This step combines Expected Scenarios (structural trends) with Unexpected Scenarios "
                    "(surprising futures) to discover business opportunities. AI pairs scenarios from both "
                    "sets, then generates concrete opportunity ideas and scores them on business impact, "
                    "unexpectedness, and plausibility."
                ).classes("text-sm text-gray-500 leading-relaxed")

        step_tab(t_d, "D", "run_d", extra=d_extra)

        # ═══ RESULTS ═══
        with ui.tab_panel(t_res):
          with ui.column().classes("w-full"):
            with ui.column().classes("w-full max-w-3xl mx-auto py-4 gap-4"):
                ui.label("Results").classes("text-lg font-semibold text-gray-800")
                ui.label("Reports will appear here after running the pipeline.").classes("text-sm text-gray-500 -mt-2")

                rbox = ui.column().classes("w-full gap-3")

                def _rebuild_results():
                    rbox.clear()
                    files = [
                        ("A1 Expected Scenarios", "A1_expected_scenarios", "blue"),
                        ("B Selected Weak Signals", "B_selected_weak_signals", "teal"),
                        ("C Unexpected Scenarios", "C_unexpected_scenarios", "orange"),
                        ("D Opportunity Scenarios", "D_opportunity_scenarios", "purple"),
                    ]
                    has_any = any((cfg.OUTPUT_DIR / f"{base}_ja.json").exists() for _, base, _ in files)
                    with rbox:
                        if not has_any:
                            with ui.column().classes("w-full items-center py-16"):
                                ui.icon("inbox", size="2rem").classes("text-gray-200 mb-2")
                                ui.label("No reports yet. Run the pipeline to generate results.").classes("text-sm text-gray-500")
                            return
                        # D matrix at top if exists
                        d_ja = cfg.OUTPUT_DIR / "D_opportunity_scenarios_ja.json"
                        if d_ja.exists():
                            with ui.card().classes("w-full card-s p-5"):
                                with ui.row().classes("items-center gap-2 mb-2"):
                                    ui.icon("scatter_plot", size="sm").classes("text-purple-500")
                                    ui.label("Opportunity Matrix — Unexpectedness × Impact").classes("font-semibold text-gray-700")
                                render_d_matrix()
                        # Cost summary card
                        cost_path = cfg.OUTPUT_DIR / "cost_report.json"
                        if cost_path.exists():
                            try:
                                cost = read_json(cost_path)
                                total = cost.get("total", {})
                                by_step = cost.get("by_step", {})
                                total_usd = total.get("cost_usd", 0)
                                total_calls = total.get("calls", 0)
                                total_tokens = total.get("total_tokens", 0)
                                with ui.card().classes("w-full card-s p-5"):
                                    with ui.row().classes("items-center gap-2 mb-2"):
                                        ui.icon("payments", size="sm").classes("text-emerald-500")
                                        ui.label("Cost Summary").classes("font-semibold text-gray-700")
                                    with ui.row().classes("items-baseline gap-4 mb-2"):
                                        ui.label(f"${total_usd:.2f}").classes("text-2xl font-semibold text-emerald-700")
                                        ui.label(f"{total_calls} calls · {total_tokens:,} tokens").classes("text-xs text-gray-500")
                                    if by_step:
                                        with ui.expansion("Per-step breakdown", icon="list").classes("w-full").props("dense"):
                                            for step_name, stats in sorted(
                                                by_step.items(), key=lambda kv: -(kv[1].get("cost_usd") or 0)
                                            ):
                                                usd = stats.get("cost_usd", 0) or 0
                                                calls = stats.get("calls", 0) or 0
                                                model = stats.get("model", "")
                                                with ui.row().classes("w-full items-center gap-2 py-1"):
                                                    ui.label(step_name).classes("text-xs font-medium text-gray-700 flex-grow")
                                                    ui.label(model).classes("text-xs text-gray-400")
                                                    ui.label(f"{calls} calls").classes("text-xs text-gray-500")
                                                    ui.label(f"${usd:.3f}").classes("text-xs font-mono text-emerald-700")
                            except Exception:
                                pass

                        # Downloads card
                        with ui.card().classes("w-full card-s p-5"):
                            ui.label("Downloads").classes("font-semibold text-gray-700 mb-2")
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
                                with ui.row().classes("w-full items-center gap-3 py-2 border-b border-gray-100"):
                                    ui.label(label).classes(f"text-sm font-medium text-{color}-700 flex-grow")
                                    ui.label(f"{count} items").classes("text-xs text-gray-500")
                                    if xlsx.exists():
                                        ui.button("Excel", icon="download", on_click=lambda p=xlsx: ui.download(str(p))).props(f"flat no-caps size=sm color={color}")
                                    ui.button("JSON", icon="download", on_click=lambda p=ja: ui.download(str(p))).props(f"flat no-caps size=sm color=grey")

                        # PowerPoint export card
                        with ui.card().classes("w-full card-s p-5"):
                            with ui.row().classes("items-center gap-2 mb-2"):
                                ui.icon("slideshow", size="sm").classes("text-indigo-500")
                                ui.label("PowerPoint Report").classes("font-semibold text-gray-700")
                            ui.label("Build a Japanese PowerPoint deck from the current Expected, Unexpected, and Opportunity scenarios.").classes("text-xs text-gray-500 mb-2")
                            pptx_status = ui.label("").classes("text-xs text-gray-600")

                            async def _gen_pptx():
                                import subprocess
                                pptx_status.text = "Generating..."
                                pptx_status.classes(replace="text-xs text-amber-600")
                                try:
                                    subdir = cfg.OUTPUT_DIR.relative_to(cfg.BASE_DIR)
                                    r = await asyncio.get_event_loop().run_in_executor(
                                        None,
                                        lambda: subprocess.run(
                                            ["node", "generate_pptx.js"],
                                            cwd=str(cfg.BASE_DIR),
                                            env={**os.environ, "PPTX_BASE": str(subdir), "PPTX_LANGS": "ja"},
                                            capture_output=True, text=True, timeout=120,
                                        ),
                                    )
                                    if r.returncode == 0:
                                        pptx_status.text = "✓ PPT generated."
                                        pptx_status.classes(replace="text-xs text-green-600")
                                        # Wait briefly for filesystem flush, then re-render so download buttons appear
                                        await asyncio.sleep(0.5)
                                        _rebuild_results()
                                    else:
                                        err = (r.stderr or r.stdout or "unknown error")[:300]
                                        pptx_status.text = f"Error: {err}"
                                        pptx_status.classes(replace="text-xs text-red-600")
                                except FileNotFoundError:
                                    pptx_status.text = "Error: `node` not installed. Install Node.js first."
                                    pptx_status.classes(replace="text-xs text-red-600")
                                except Exception as e:
                                    pptx_status.text = f"Error: {e}"
                                    pptx_status.classes(replace="text-xs text-red-600")

                            with ui.row().classes("items-center gap-2"):
                                ui.button("Generate PPT", icon="slideshow", on_click=_gen_pptx).props("unelevated no-caps size=sm color=indigo")
                                # Japanese download only (zh generation removed)
                                pptx_path = cfg.OUTPUT_DIR / "JRI_Aging_Report_ja.pptx"
                                if pptx_path.exists():
                                    ui.button("Download JA", icon="download",
                                              on_click=lambda p=pptx_path: ui.download(str(p))).props("flat no-caps size=sm color=indigo")

                from utils.data_io import read_json
                _rebuild_results()
                with ui.row().classes("w-full justify-end"):
                    ui.button("Refresh", icon="refresh", on_click=_rebuild_results).props("flat no-caps size=sm color=grey")

                # Auto-refresh results card when user switches to this tab — so
                # counts reflect the latest run (previously the card was built once
                # and never re-read the output files).
                state["_rebuild_results"] = _rebuild_results

    # Footer
    with ui.row().classes("w-full justify-center py-3 border-t border-gray-100 mt-4"):
        ui.label(f"JRI Living Lab+ Pipeline · {_version_info()}").classes("text-xs text-gray-500")

    h = LogHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(h)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="JRI Pipeline",
        port=8080,
        reload=False,
        storage_secret=os.getenv("STORAGE_SECRET", "jri-pipeline-secret-2026"),
    )
