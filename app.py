"""
JRI Pipeline V2 — Web UI (NiceGUI)
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from nicegui import ui

import config as cfg
from config import UI_PARAMS, apply_overrides

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ─── State ──────────────────────────────────────────
state = {"running": False, "step": "", "logs": [], "last_run": None, "last_summary": None}

LABELS = {
    "a1_cluster_generate": "A1 Cluster + Generate",
    "rerank_a": "A1 Re-rank", "b_select": "B Select",
    "b_dedup": "B Dedup", "c_cluster": "C Group",
    "c_generate": "C Generate", "c_rank": "C Rank",
    "d_pair": "D Pair", "d_generate": "D Generate",
    "d_rank": "D Rank", "rerank_c": "C Re-rank", "rerank_d": "D Re-rank",
}

# Estimated time per action
EST_TIME = {
    "a1_cluster_generate": "~5-10 min, ~$3-5",
    "rerank_a": "~2-3 min, ~$1",
    "b_select": "< 10 sec, free",
    "b_dedup": "~2-3 min, ~$1",
    "c_cluster": "~1-2 min, ~$1",
    "c_generate": "~5-15 min, ~$5-10",
    "c_rank": "~2-3 min, ~$1",
    "rerank_c": "~2-3 min, ~$1",
    "d_pair": "~1-2 min, ~$0.5",
    "d_generate": "~3-8 min, ~$3-5",
    "d_rank": "~2-3 min, ~$1",
    "rerank_d": "~2-3 min, ~$1",
}

# Action dependencies: key = step_key, value = intermediate file that must exist
ACTION_DEPS = {
    "c_generate": ("c_phase1_clusters.json", "Run 'Group Signals' first"),
    "c_rank": ("c_phase2_scenarios.json", "Run 'Generate' first"),
    "d_generate": ("d_phase1_pairs.json", "Run 'Create Pairs' first"),
    "d_rank": ("d_phase2_scenarios.json", "Run 'Generate' first"),
    "rerank_a": ("a1_phase3_scenarios.json", "Run A1 first"),
    "rerank_c": ("c_phase2_scenarios.json", "Run C Generate first"),
    "rerank_d": ("d_phase2_scenarios.json", "Run D Generate first"),
}

# What each action replaces + downstream impact
ACTION_IMPACT = {
    "a1_cluster_generate": ("Replaces: A1 theme clusters + generated scenarios.",
                            "You will need to re-run A1 Re-rank and Step D afterward."),
    "rerank_a": ("Replaces: A1 final scored/filtered results.", ""),
    "b_select": ("Replaces: B signal selection.", "You may want to re-run B Dedup afterward."),
    "b_dedup": ("Replaces: B deduplicated signals.",
                "Step C uses these signals — re-run C if you want updated results."),
    "c_cluster": ("Replaces: C signal groupings.",
                  "You will need to re-run C Generate and C Rank afterward."),
    "c_generate": ("Replaces: C generated scenarios.",
                   "You will need to re-run C Rank afterward. Step D uses C results."),
    "c_rank": ("Replaces: C final scored/filtered results.",
               "Step D uses these results — re-run D if you want updated opportunities."),
    "d_pair": ("Replaces: D pair selection.",
               "You will need to re-run D Generate and D Rank afterward."),
    "d_generate": ("Replaces: D generated opportunity scenarios.",
                   "You will need to re-run D Rank afterward."),
    "d_rank": ("Replaces: D final scored/filtered/classified results.", ""),
    "rerank_c": ("Replaces: C final scored/filtered results.", ""),
    "rerank_d": ("Replaces: D final scored/filtered results.", ""),
}

STEPS_INFO = {
    "A1": {"icon": "article", "color": "blue", "title": "Expected Scenarios",
           "desc": "Identify structural changes from news articles.",
           "depends": None,
           "check_file": "a1_phase3_scenarios.json",
           "output_file": "A1_expected_scenarios_ja.json"},
    "B":  {"icon": "sensors", "color": "green", "title": "Weak Signal Selection",
           "desc": "Score, rank and filter weak signals.",
           "depends": None,
           "check_file": "b_phase3_dedup_selected.json",
           "output_file": "B_selected_weak_signals_ja.json"},
    "C":  {"icon": "bolt", "color": "purple", "title": "Unexpected Scenarios",
           "desc": "Generate surprising futures from weak signals.",
           "depends": "B",
           "check_file": "c_phase2_scenarios.json",
           "output_file": "C_unexpected_scenarios_ja.json"},
    "D":  {"icon": "lightbulb", "color": "amber", "title": "Opportunity Scenarios",
           "desc": "Cross A1 x C for business opportunities.",
           "depends": "A1+C",
           "check_file": "d_phase2_scenarios.json",
           "output_file": "D_opportunity_scenarios_ja.json"},
}


def step_status(code):
    """Return (status_str, detail_str, timestamp_str).
    Prioritizes final output count over intermediate count."""
    from utils.data_io import read_json
    info = STEPS_INFO[code]

    # Check final output first
    output_path = cfg.OUTPUT_DIR / info["output_file"]
    if output_path.exists():
        data = read_json(output_path)
        mtime = datetime.fromtimestamp(output_path.stat().st_mtime).strftime("%m/%d %H:%M")
        if data:
            return ("done", f"{len(data)} delivered", mtime)

    # Fallback to intermediate
    path = cfg.INTERMEDIATE_DIR / info["check_file"]
    if path.exists():
        data = read_json(path)
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%m/%d %H:%M")
        if data:
            return ("done", f"{len(data)} candidates", mtime)
        return ("empty", "0 items", mtime)
    return ("pending", "Not started", "")


def check_dep(step_key):
    """Return (can_run: bool, message: str)."""
    if step_key not in ACTION_DEPS:
        return True, ""
    dep_file, msg = ACTION_DEPS[step_key]
    path = cfg.INTERMEDIATE_DIR / dep_file
    return path.exists(), msg


def build_summary(step_key):
    """Build a result summary after a run, including preview titles."""
    try:
        from utils.data_io import read_json
        summary_map = {
            "a1_cluster_generate": ("a1_phase3_scenarios.json", "scenarios generated", "title_ja"),
            "b_select": ("b_phase2_top3000_candidates.json", "signals selected", "title_ja"),
            "b_dedup": ("b_phase3_dedup_selected.json", "signals after dedup", "title_ja"),
            "c_cluster": ("c_phase1_clusters.json", "signal groups created", "theme_ja"),
            "c_generate": ("c_phase2_scenarios.json", "scenarios generated", "title_ja"),
            "d_pair": ("d_phase1_pairs.json", "pairs created", None),
            "d_generate": ("d_phase2_scenarios.json", "scenarios generated", "opportunity_title_ja"),
        }
        info = summary_map.get(step_key)
        if info:
            fname, label, title_key = info
            data = read_json(cfg.INTERMEDIATE_DIR / fname)
            previews = []
            if title_key:
                for item in data[:3]:
                    t = item.get(title_key, item.get("title", ""))
                    if t:
                        previews.append(t[:40])
            return {"count": len(data), "label": label, "previews": previews}

        # For rank/rerank steps, check output files
        output_map = {
            "c_rank": ("C_unexpected_scenarios_ja.json", "title_ja"),
            "d_rank": ("D_opportunity_scenarios_ja.json", "opportunity_title_ja"),
            "rerank_a": ("A1_expected_scenarios_ja.json", "title_ja"),
            "rerank_c": ("C_unexpected_scenarios_ja.json", "title_ja"),
            "rerank_d": ("D_opportunity_scenarios_ja.json", "opportunity_title_ja"),
        }
        if step_key in output_map:
            fname, title_key = output_map[step_key]
            opath = cfg.OUTPUT_DIR / fname
            if opath.exists():
                data = read_json(opath)
                previews = [item.get(title_key, "")[:40] for item in data[:3] if item.get(title_key)]
                return {"count": len(data), "label": "scenarios passed all filters", "previews": previews}
        return None
    except Exception:
        return None


class LogHandler(logging.Handler):
    def emit(self, record):
        state["logs"].append(self.format(record))
        if len(state["logs"]) > 300:
            state["logs"] = state["logs"][-300:]


async def run_step(step, overrides, status_el, indicator, log_area, summary_box, progress_bar=None):
    if state["running"]:
        ui.notify("Already running — please wait.", type="warning")
        return

    # Check dependency
    can_run, dep_msg = check_dep(step)
    if not can_run:
        ui.notify(f"Cannot run: {dep_msg}", type="negative")
        return

    state.update(running=True, step=step, logs=[], last_summary=None)
    apply_overrides(overrides)
    label = LABELS.get(step, step)
    status_el.text = f"Running {label}..."
    status_el.classes(replace="text-amber-600 font-semibold text-sm")
    indicator.visible = True
    if progress_bar:
        progress_bar.visible = True
    log_area.clear()

    # Clear summary
    summary_box.clear()
    with summary_box:
        with ui.row().classes("items-center gap-2 py-3"):
            ui.spinner("dots", size="sm")
            ui.label(f"Running {label}...").classes("text-sm text-gray-500")

    def _run():
        try:
            if step == "a1_cluster_generate":
                from steps.step_a1 import phase2_cluster, phase3_generate
                phase3_generate(phase2_cluster())
            elif step == "rerank_a":
                from rerank import rerank_a; rerank_a()
            elif step == "b_select":
                from steps.step_b import select_top_signals; select_top_signals()
            elif step == "b_dedup":
                from steps.step_b import diversity_dedup; diversity_dedup()
            elif step == "c_cluster":
                from steps.step_c import phase1_cluster, phase1_random
                (phase1_random if cfg.C_MODE == "random" else phase1_cluster)()
            elif step == "c_generate":
                from steps.step_c import phase2_generate; phase2_generate()
            elif step == "c_rank":
                from steps.step_c import phase3_rank; phase3_rank()
            elif step == "rerank_c":
                from rerank import rerank_c; rerank_c()
            elif step == "d_pair":
                from steps.step_d import phase1_select_pairs, phase1_random_pairs
                (phase1_random_pairs if cfg.D_MODE == "random" else phase1_select_pairs)()
            elif step == "d_generate":
                from steps.step_d import phase2_generate; phase2_generate()
            elif step == "d_rank":
                from steps.step_d import phase3_rank; phase3_rank()
            elif step == "rerank_d":
                from rerank import rerank_d; rerank_d()
            state["last_summary"] = build_summary(step)
            state["logs"].append(f"Completed: {label}")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            state["last_summary"] = {"error": str(e)}
        finally:
            state.update(running=False, last_run=datetime.now().strftime("%H:%M:%S"))

    await asyncio.get_event_loop().run_in_executor(None, _run)


# ─── Components ─────────────────────────────────────

def render_settings(section, params, show_advanced=True):
    items = [(k, v) for k, v in UI_PARAMS.items() if v["section"] == section]
    main_items = [(k, v) for k, v in items if v.get("priority") == "main"]
    adv_items = [(k, v) for k, v in items if v.get("priority") == "advanced"]

    def _item(key, spec):
        default = spec["default"]
        params.setdefault(key, default)
        hint = spec.get("hint", "")
        if spec["type"] == "number":
            with ui.column().classes("w-full gap-0 py-1"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label(spec["label"]).classes("text-sm text-gray-700")
                    n = ui.number(value=default, min=spec.get("min", 0), max=spec.get("max", 100)
                    ).classes("w-24").props("dense outlined")
                    n.on_value_change(lambda e, k=key: params.update({k: e.value}))
                if hint:
                    ui.label(hint).classes("text-xs text-gray-400 -mt-1")
        elif spec["type"] == "bool":
            with ui.column().classes("w-full gap-0 py-1"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label(spec["label"]).classes("text-sm text-gray-700")
                    s = ui.switch(value=default).props("dense")
                    s.on_value_change(lambda e, k=key: params.update({k: e.value}))
                if hint:
                    ui.label(hint).classes("text-xs text-gray-400")
        elif spec["type"] == "select":
            with ui.column().classes("w-full gap-0 py-1"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label(spec["label"]).classes("text-sm text-gray-700")
                    sel = ui.select(spec["options"], value=default).classes("w-40").props("dense outlined")
                    sel.on_value_change(lambda e, k=key: params.update({k: e.value}))
                if hint:
                    ui.label(hint).classes("text-xs text-gray-400")
        elif spec["type"] == "text":
            with ui.column().classes("w-full gap-0 py-1"):
                inp = ui.input(label=spec["label"], value=str(default)).classes("w-full").props("dense outlined")
                inp.on_value_change(lambda e, k=key: params.update({k: e.value}))
                if hint:
                    ui.label(hint).classes("text-xs text-gray-400")

    for key, spec in main_items:
        _item(key, spec)
    if adv_items and show_advanced:
        with ui.expansion("Advanced Filters", icon="tune").classes("w-full text-sm").props("dense"):
            for key, spec in adv_items:
                _item(key, spec)


# ─── Page ───────────────────────────────────────────

@ui.page("/")
def main_page():
    ui.add_head_html("""<style>
        body { background: #f7f8fa; }
        .card-s { border-radius: 14px !important; border: 1px solid #ebedf0 !important;
                  box-shadow: none !important; }
        .card-s:hover { border-color: #dcdfe3 !important; }
        .hero-bg { background: #111827; border-radius: 16px !important; }
        .st-done { background: #ecfdf5; color: #065f46; }
        .st-wait { background: #f3f4f6; color: #6b7280; }
        .summary-ok { background: #f0fdf4; border: 1px solid #d1fae5; border-radius: 10px; }
        .summary-err { background: #fef2f2; border: 1px solid #fee2e2; border-radius: 10px; }
        .est-chip { color: #9ca3af; font-size: 11px; }
        .q-tab { text-transform: none !important; font-size: 13px !important; }
        .q-btn { text-transform: none !important; }
    </style>""")

    params = {}
    log_ref = [None]
    summary_ref = [None]

    # ─── Header ─────────────────────────
    with ui.column().classes("w-full gap-0"):
        with ui.row().classes("w-full bg-white border-b border-gray-100 px-6 py-2.5 items-center justify-between"):
            with ui.row().classes("items-center gap-2.5"):
                ui.label("JRI").classes("text-xs font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded")
                ui.label("Living Lab+ Pipeline").classes("text-sm font-semibold text-gray-700")
            with ui.row().classes("items-center gap-3"):
                indicator = ui.spinner("dots", size="xs", color="amber")
                indicator.visible = False
                status_el = ui.label("Ready").classes("text-xs font-medium text-emerald-600")
        progress_bar = ui.linear_progress(show_value=False).classes("w-full").props("indeterminate color=amber size=2px")
        progress_bar.visible = False

    # ─── Tabs ───────────────────────────
    with ui.tabs().classes("w-full bg-white border-b px-4").props(
        "active-color=blue-8 indicator-color=blue-8 dense align=left"
    ) as tabs:
        t0 = ui.tab("dashboard", label="Dashboard", icon="dashboard")
        t1 = ui.tab("a1", label="A1", icon="article")
        t2 = ui.tab("b", label="B", icon="sensors")
        t3 = ui.tab("c", label="C", icon="bolt")
        t4 = ui.tab("d", label="D", icon="lightbulb")
        t5 = ui.tab("results", label="Results", icon="download")

    with ui.tab_panels(tabs, value=t0).classes("w-full flex-grow bg-transparent"):

        # ══════════════════════════════════
        #  DASHBOARD
        # ══════════════════════════════════
        with ui.tab_panel(t0):
            with ui.column().classes("w-full max-w-5xl mx-auto py-6 gap-6"):
                with ui.card().classes("w-full hero-bg text-white p-8"):
                    ui.label("Scenario Analysis").classes("text-2xl font-bold mb-1")
                    ui.label(
                        "Generate foresight reports in 4 steps. Configure, run, download."
                    ).classes("text-sm opacity-60 mb-5")
                    ui.button("Start with A1  →", icon="arrow_forward",
                        on_click=lambda: tabs.set_value("a1")
                    ).props("color=white text-color=grey-9 unelevated size=sm")

                # Pipeline Status
                with ui.card().classes("w-full card-s p-6"):
                    ui.label("Pipeline Status").classes("text-lg font-bold text-gray-800 mb-4")
                    status_ctr = ui.column().classes("w-full gap-2")

                    def refresh_status():
                        status_ctr.clear()
                        with status_ctr:
                            for code, info in STEPS_INFO.items():
                                st, detail, mtime = step_status(code)
                                with ui.card().classes("w-full p-4 cursor-pointer").on(
                                    "click", lambda c=code: tabs.set_value(c.lower() if len(c) == 1 else "a1")
                                ):
                                    with ui.row().classes("w-full items-center gap-4"):
                                        with ui.element("div").classes(
                                            f"w-10 h-10 rounded-xl bg-{info['color']}-100 flex items-center justify-center shrink-0"
                                        ):
                                            ui.icon(info["icon"], size="sm").classes(f"text-{info['color']}-600")
                                        with ui.column().classes("flex-grow gap-0"):
                                            with ui.row().classes("items-center gap-2"):
                                                ui.label(f"Step {code}").classes("font-bold text-gray-800")
                                                ui.label(info["title"]).classes("text-sm text-gray-500")
                                            if info["depends"]:
                                                ui.label(f"Requires {info['depends']}").classes("text-xs text-gray-400")
                                        if st == "done":
                                            with ui.column().classes("items-end gap-0"):
                                                with ui.element("div").classes("st-done px-3 py-1 rounded-full text-xs font-semibold"):
                                                    ui.label(f"Done — {detail}")
                                                ui.label(mtime).classes("text-xs text-gray-400 mt-0.5")
                                        else:
                                            with ui.element("div").classes("st-wait px-3 py-1 rounded-full text-xs font-semibold"):
                                                ui.label("Not started")
                                        ui.icon("chevron_right").classes("text-gray-300")

                    refresh_status()
                    ui.button("Refresh", icon="refresh", on_click=refresh_status).props("flat size=sm color=blue").classes("mt-2")

                with ui.row().classes("w-full gap-5"):
                    with ui.card().classes("flex-1 card-s p-5"):
                        with ui.row().classes("items-center gap-2 mb-3"):
                            ui.icon("database", size="sm").classes("text-teal-500")
                            ui.label("Data").classes("font-bold text-gray-700")
                        ui.label("Current datasets (upload coming soon):").classes("text-xs text-gray-400 mb-2")
                        for f in [cfg.A1_INPUT_FILE, cfg.B_INPUT_FILE]:
                            with ui.row().classes("items-center gap-2 py-1"):
                                ui.icon("description", size="xs").classes("text-teal-400")
                                ui.label(f.name).classes("text-xs text-gray-600 font-mono")
                        with ui.row().classes("mt-2 bg-blue-50 rounded-lg px-3 py-2 items-start gap-2"):
                            ui.icon("info", size="xs").classes("text-blue-500 mt-0.5")
                            ui.label(
                                "Changing the Research Topic adjusts how AI scores and generates scenarios, "
                                "but the underlying data stays the same. "
                                "To analyze a completely different topic, new datasets need to be uploaded."
                            ).classes("text-xs text-blue-700")

                    with ui.card().classes("flex-1 card-s p-5"):
                        with ui.row().classes("items-center gap-2 mb-3"):
                            ui.icon("public", size="sm").classes("text-blue-500")
                            ui.label("Global Settings").classes("font-bold text-gray-700")
                        render_settings("Global", params, show_advanced=False)

                with ui.card().classes("w-full card-s p-6"):
                    with ui.expansion("What does each step do?", icon="help_outline").classes("w-full").props("dense"):
                        defs = [
                            ("A1 — Expected", "Structural, irreversible changes likely in the next decade."),
                            ("B — Weak Signals", "Early signs outside your normal radar with potential societal impact."),
                            ("C — Unexpected", "Surprising futures that even experts can't predict."),
                            ("D — Opportunity", "Non-obvious business opportunities from crossing Expected x Unexpected."),
                        ]
                        for title, desc in defs:
                            with ui.row().classes("py-1 items-start gap-2"):
                                ui.label(title).classes("text-sm font-semibold text-gray-700 w-36 shrink-0")
                                ui.label(desc).classes("text-sm text-gray-500")

        # ══════════════════════════════════
        #  STEP TAB BUILDER
        # ══════════════════════════════════
        def make_step_tab(panel, code, phases, locked_note, section, actions, extra_content=None):
            info = STEPS_INFO[code]
            with ui.tab_panel(panel):
                with ui.column().classes("w-full max-w-4xl mx-auto py-6 gap-5"):

                    # Header
                    st, detail, mtime = step_status(code)
                    with ui.row().classes("w-full items-center justify-between px-1"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon(info["icon"], size="sm").classes("text-gray-400")
                            with ui.column().classes("gap-0"):
                                ui.label(f"Step {code} — {info['title']}").classes("text-lg font-semibold text-gray-800")
                                ui.label(info["desc"]).classes("text-xs text-gray-400")
                        with ui.column().classes("items-end gap-0"):
                            if st == "done":
                                ui.badge(f"Done — {detail}", color="green").classes("text-xs")
                                ui.label(mtime).classes("text-xs text-gray-300 mt-0.5")
                            else:
                                ui.badge("Not started", color="grey").classes("text-xs")

                    # Extra content (e.g. mode comparison for C)
                    if extra_content:
                        extra_content()

                    # Two columns
                    with ui.row().classes("w-full gap-5 items-start"):
                        with ui.card().classes("flex-1 card-s p-5"):
                            ui.label("What happens").classes("text-xs font-bold text-gray-400 uppercase tracking-widest mb-3")
                            for i, (text, locked) in enumerate(phases):
                                with ui.row().classes("items-center gap-3 py-1"):
                                    if locked:
                                        ui.icon("lock", size="xs").classes("text-gray-300")
                                    else:
                                        ui.icon("radio_button_unchecked", size="xs").classes(f"text-{info['color']}-400")
                                    ui.label(text).classes(f"text-sm {'text-gray-300' if locked else 'text-gray-700'}")
                            if locked_note:
                                with ui.row().classes("mt-3 bg-amber-50 rounded-lg px-3 py-2 items-center gap-2"):
                                    ui.icon("info", size="xs").classes("text-amber-500")
                                    ui.label(locked_note).classes("text-xs text-amber-700")

                        with ui.card().classes("flex-1 card-s p-5"):
                            ui.label("Settings").classes("text-xs font-bold text-gray-400 uppercase tracking-widest mb-3")
                            render_settings(section, params)

                    # Run + Summary
                    with ui.card().classes("w-full card-s p-5"):
                        ui.label("Run").classes("text-xs font-bold text-gray-400 uppercase tracking-widest mb-3")

                        # Summary box (shows result after run)
                        summary_box = ui.column().classes("w-full mb-3")
                        if not summary_ref[0]:
                            summary_ref[0] = summary_box

                        action_buttons = []  # (btn, step_key, dep_msg) for reactive updates
                        with ui.row().classes("gap-3 flex-wrap items-center"):
                            for i, (lbl, icn, key, is_outline, est) in enumerate(actions):
                                can, dep_msg = check_dep(key)
                                props = "color=indigo size=sm"
                                if is_outline:
                                    props += " outline"
                                if not can:
                                    props += " disable"

                                with ui.column().classes("gap-1"):
                                    async def _click(k=key, sb=summary_box):
                                        if k not in ("b_select",):
                                            replaces, downstream = ACTION_IMPACT.get(k, ("", ""))
                                            with ui.dialog() as dlg, ui.card().classes("p-5 max-w-md"):
                                                ui.label("Confirm Run").classes("text-lg font-bold mb-2")
                                                ui.label(f"This will run: {LABELS.get(k, k)}").classes("text-sm text-gray-600")
                                                with ui.row().classes("items-center gap-2 mt-2"):
                                                    ui.icon("schedule", size="xs").classes("text-gray-400")
                                                    ui.label(f"Estimated: {EST_TIME.get(k, 'unknown')}").classes("text-sm text-gray-400")
                                                ui.label("API cost is incurred each time you run.").classes("text-xs text-gray-400 mt-1")
                                                if replaces:
                                                    ui.separator().classes("my-2")
                                                    with ui.row().classes("items-start gap-2"):
                                                        ui.icon("warning", size="xs").classes("text-orange-500 mt-0.5")
                                                        with ui.column().classes("gap-0"):
                                                            ui.label(replaces).classes("text-xs text-orange-600")
                                                            if downstream:
                                                                ui.label(downstream).classes("text-xs text-orange-400 mt-1")
                                                with ui.row().classes("mt-4 gap-2 justify-end"):
                                                    ui.button("Cancel", on_click=dlg.close).props("flat")
                                                    ui.button("Run", icon="play_arrow",
                                                        on_click=lambda d=dlg: (d.close(), None) or asyncio.ensure_future(
                                                            run_step(k, params, status_el, indicator, log_ref[0] or ui.log(), sb, progress_bar)
                                                        )
                                                    ).props("color=indigo")
                                            dlg.open()
                                        else:
                                            await run_step(k, params, status_el, indicator, log_ref[0] or ui.log(), sb, progress_bar)

                                    step_num = f"Step {i+1}: " if len(actions) > 1 else ""
                                    btn = ui.button(f"{step_num}{lbl}", icon=icn, on_click=_click).props(props)
                                    if not can:
                                        btn.tooltip(dep_msg)
                                    action_buttons.append((btn, key))
                                    ui.html(f'<span class="est-chip">{est}</span>')

                    # Log (collapsed)
                    with ui.expansion("Execution Log", icon="terminal").classes("w-full").props("dense"):
                        la = ui.log(max_lines=100).classes(
                            "w-full h-40 bg-gray-900 text-green-400 rounded-lg text-xs font-mono"
                        )
                        if not log_ref[0]:
                            log_ref[0] = la

                        def tick(area=la, sb=summary_box if summary_ref[0] else None, btns=action_buttons):
                            for line in state["logs"]:
                                area.push(line)
                            state["logs"] = []
                            if not state["running"] and state.get("last_run"):
                                status_el.text = f"Done ({state['last_run']})"
                                status_el.classes(replace="text-green-600 font-semibold text-sm")
                                indicator.visible = False
                                if progress_bar:
                                    progress_bar.visible = False
                                # Update button disabled states reactively
                                for btn, key in btns:
                                    can, _ = check_dep(key)
                                    if can:
                                        btn.props(remove="disable")
                                    else:
                                        btn.props(add="disable")
                                # Show summary
                                s = state.get("last_summary")
                                if s and sb:
                                    sb.clear()
                                    with sb:
                                        if "error" in s:
                                            with ui.column().classes("summary-err p-4 gap-1"):
                                                with ui.row().classes("items-center gap-2"):
                                                    ui.icon("error", size="sm").classes("text-red-500")
                                                    ui.label(f"Error: {s['error'][:100]}").classes("text-sm text-red-700")
                                        elif "count" in s:
                                            with ui.column().classes("summary-ok p-4 gap-2"):
                                                with ui.row().classes("items-center gap-3"):
                                                    ui.icon("check_circle", size="sm").classes("text-green-500")
                                                    ui.label(f"{s['count']} {s['label']}").classes("text-sm font-semibold text-green-700")
                                                previews = s.get("previews", [])
                                                if previews:
                                                    ui.label("Preview:").classes("text-xs text-gray-400 mt-1")
                                                    for p in previews:
                                                        with ui.row().classes("items-center gap-2"):
                                                            ui.icon("chevron_right", size="xs").classes("text-green-300")
                                                            ui.label(p).classes("text-xs text-gray-600")
                                    state["last_summary"] = None  # show once
                        ui.timer(1.0, tick)

                    # Next step
                    next_map = {"A1": ("b", "B — Weak Signals"), "B": ("c", "C — Unexpected"),
                                "C": ("d", "D — Opportunity"), "D": ("results", "Download Reports")}
                    if code in next_map:
                        tab_key, next_label = next_map[code]
                        with ui.row().classes("w-full justify-end"):
                            ui.button(f"Next: {next_label}  →", icon="arrow_forward",
                                on_click=lambda tk=tab_key: tabs.set_value(tk)
                            ).props("flat color=blue")

        # ─── A1 ────────────────────────
        make_step_tab(t1, "A1",
            [("Summarize articles", True), ("Cluster into themes", False),
             ("Generate scenarios", False), ("Score and filter", False)],
            "Summarization is already done. You can re-run from clustering onward.",
            "A1 Expected",
            [("Cluster + Generate", "hub", "a1_cluster_generate", False, EST_TIME["a1_cluster_generate"]),
             ("Re-rank Only", "sort", "rerank_a", True, EST_TIME["rerank_a"])])

        # ─── B ─────────────────────────
        make_step_tab(t2, "B",
            [("Score all signals", True), ("Apply thresholds, select top N", False),
             ("Remove near-duplicates", False)],
            "Signal scoring is already done. You can adjust thresholds and re-select.",
            "B Weak Signal",
            [("Select Top N", "filter_alt", "b_select", False, EST_TIME["b_select"]),
             ("Diversity Dedup", "content_cut", "b_dedup", True, EST_TIME["b_dedup"])])

        # ─── C (with mode comparison) ──
        def c_extra():
            with ui.card().classes("w-full card-s p-5"):
                with ui.row().classes("items-center gap-2 mb-3"):
                    ui.icon("compare", size="sm").classes("text-purple-500")
                    ui.label("Grouping Mode Comparison").classes("text-sm font-bold text-gray-700")
                with ui.row().classes("w-full gap-4"):
                    with ui.card().classes("flex-1 bg-purple-50 border border-purple-200 p-4"):
                        ui.label("Cluster Mode").classes("font-bold text-purple-700 mb-1")
                        ui.label("Groups similar signals together using AI.").classes("text-sm text-gray-600 mb-2")
                        pros = ["Comprehensive topic coverage", "No important signal left out", "Consistent, repeatable results"]
                        for p in pros:
                            with ui.row().classes("items-center gap-1"):
                                ui.icon("add", size="xs").classes("text-green-500")
                                ui.label(p).classes("text-xs text-gray-500")
                        with ui.row().classes("items-center gap-1 mt-1"):
                            ui.icon("remove", size="xs").classes("text-red-400")
                            ui.label("May miss cross-domain creative connections").classes("text-xs text-gray-500")

                    with ui.card().classes("flex-1 bg-amber-50 border border-amber-200 p-4"):
                        ui.label("Random Mode").classes("font-bold text-amber-700 mb-1")
                        ui.label("Randomly mixes signals from different areas.").classes("text-sm text-gray-600 mb-2")
                        pros = ["Forces unexpected combinations", "Mimics human brainstorming leaps", "Different results each run"]
                        for p in pros:
                            with ui.row().classes("items-center gap-1"):
                                ui.icon("add", size="xs").classes("text-green-500")
                                ui.label(p).classes("text-xs text-gray-500")
                        with ui.row().classes("items-center gap-1 mt-1"):
                            ui.icon("remove", size="xs").classes("text-red-400")
                            ui.label("Some combinations may not produce useful scenarios").classes("text-xs text-gray-500")

        make_step_tab(t3, "C",
            [("Group signals (cluster or random)", False),
             ("Generate unexpected scenarios", False),
             ("Score and filter", False)],
            None, "C Unexpected",
            [("Step 1: Group Signals", "hub", "c_cluster", False, EST_TIME["c_cluster"]),
             ("Step 2: Generate", "auto_awesome", "c_generate", True, EST_TIME["c_generate"]),
             ("Step 3: Rank & Filter", "sort", "c_rank", True, EST_TIME["c_rank"])],
            extra_content=c_extra)

        # ─── D ─────────────────────────
        make_step_tab(t4, "D",
            [("Select A x C pairs", False),
             ("Generate opportunity scenarios", False),
             ("Score, filter, classify into matrix", False)],
            None, "D Opportunity",
            [("Step 1: Create Pairs", "shuffle", "d_pair", False, EST_TIME["d_pair"]),
             ("Step 2: Generate", "auto_awesome", "d_generate", True, EST_TIME["d_generate"]),
             ("Step 3: Rank & Classify", "sort", "d_rank", True, EST_TIME["d_rank"])])

        # ══════════════════════════════════
        #  RESULTS
        # ══════════════════════════════════
        with ui.tab_panel(t5):
            with ui.column().classes("w-full max-w-4xl mx-auto py-6 gap-5"):
                with ui.row().classes("items-center gap-3 mb-2"):
                    ui.icon("download", size="lg").classes("text-teal-500")
                    ui.label("Download Reports").classes("text-2xl font-bold text-gray-800")
                ui.label("Your generated scenario reports.").classes("text-sm text-gray-400 mb-2")

                results_box = ui.column().classes("w-full gap-3")
                show_all = {"value": False}

                def refresh():
                    results_box.clear()
                    od = cfg.OUTPUT_DIR
                    imd = cfg.INTERMEDIATE_DIR
                    files = []
                    if od.exists():
                        if show_all["value"]:
                            files = [f for f in sorted(od.iterdir()) if f.suffix in (".pptx", ".xlsx", ".json")]
                        else:
                            files = [f for f in sorted(od.iterdir()) if f.suffix in (".pptx", ".xlsx")]
                    if not files:
                        with results_box:
                            with ui.card().classes("w-full card-s text-center py-16"):
                                ui.icon("inbox", size="3rem").classes("text-gray-200 mb-3")
                                ui.label("No reports yet").classes("text-lg text-gray-400")
                                ui.label("Run the pipeline steps to generate reports.").classes("text-sm text-gray-300")
                        return

                    reports = [f for f in files if f.suffix == ".pptx"]
                    data_files = [f for f in files if f.suffix in (".xlsx", ".json")]

                    with results_box:
                        if reports:
                            with ui.card().classes("w-full card-s p-5"):
                                with ui.row().classes("items-center gap-2 mb-3"):
                                    ui.icon("slideshow", size="sm").classes("text-red-500")
                                    ui.label("Presentation Reports").classes("font-bold text-gray-700")
                                for f in reports:
                                    kb = f.stat().st_size / 1024
                                    with ui.row().classes("w-full items-center gap-3 py-2 px-3 rounded-lg hover:bg-gray-50"):
                                        ui.badge("PPTX", color="red").classes("text-white text-xs")
                                        ui.label(f.name).classes("text-sm text-gray-700 flex-grow")
                                        ui.label(f"{kb:,.0f} KB").classes("text-xs text-gray-400")
                                        ui.button("Download", icon="download",
                                            on_click=lambda p=f: ui.download(str(p))
                                        ).props("color=red size=sm unelevated")

                        if data_files:
                            with ui.card().classes("w-full card-s p-5"):
                                with ui.row().classes("items-center gap-2 mb-3"):
                                    ui.icon("table_chart", size="sm").classes("text-green-500")
                                    ui.label("Data Exports").classes("font-bold text-gray-700")
                                for f in data_files:
                                    kb = f.stat().st_size / 1024
                                    ext = f.suffix[1:].upper()
                                    ec = {"JSON": "blue", "XLSX": "green"}.get(ext, "gray")
                                    with ui.row().classes("w-full items-center gap-3 py-1.5 px-3 rounded hover:bg-gray-50"):
                                        ui.badge(ext, color=ec).classes("text-white text-xs")
                                        ui.label(f.name).classes("text-sm text-gray-600 flex-grow font-mono")
                                        ui.label(f"{kb:,.0f} KB").classes("text-xs text-gray-400")
                                        ui.button(icon="download",
                                            on_click=lambda p=f: ui.download(str(p))
                                        ).props("flat round size=xs color=green")

                with ui.row().classes("gap-2 items-center"):
                    ui.button("Refresh", icon="refresh", on_click=refresh).props("flat color=teal")
                    def toggle_all():
                        show_all["value"] = not show_all["value"]
                        refresh()
                    ui.button(
                        "Show All Files" if not show_all["value"] else "Show Reports Only",
                        icon="visibility", on_click=toggle_all
                    ).props("flat color=gray size=sm")
                refresh()

    h = LogHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(h)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="JRI Pipeline V2", port=8080, reload=False)
