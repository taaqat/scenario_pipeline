"""
JRI Pipeline V2 — Web UI
Minimal design. Every element earns its place.
"""
import asyncio
import logging
from datetime import datetime

from nicegui import ui

import config as cfg
from config import UI_PARAMS, apply_overrides

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ─── State & Config ─────────────────────────────────
state = {"running": False, "step": "", "logs": [], "last_run": None, "last_summary": None}

LABELS = {
    "a1_cluster_generate": "A1 Cluster + Generate", "rerank_a": "A1 Re-rank",
    "b_select": "B Select", "b_dedup": "B Dedup",
    "c_cluster": "C Group", "c_generate": "C Generate", "c_rank": "C Rank",
    "d_pair": "D Pair", "d_generate": "D Generate", "d_rank": "D Rank",
    "rerank_c": "C Re-rank", "rerank_d": "D Re-rank",
}
EST = {
    "a1_cluster_generate": "5–10 min · ~$3–5", "rerank_a": "2–3 min · ~$1",
    "b_select": "instant · free", "b_dedup": "2–3 min · ~$1",
    "c_cluster": "1–2 min · ~$1", "c_generate": "5–15 min · ~$5–10", "c_rank": "2–3 min · ~$1",
    "rerank_c": "2–3 min · ~$1", "d_pair": "1–2 min · ~$0.5",
    "d_generate": "3–8 min · ~$3–5", "d_rank": "2–3 min · ~$1", "rerank_d": "2–3 min · ~$1",
}
DEPS = {
    "c_generate": ("c_phase1_clusters.json", "Run Group Signals first"),
    "c_rank": ("c_phase2_scenarios.json", "Run Generate first"),
    "d_generate": ("d_phase1_pairs.json", "Run Create Pairs first"),
    "d_rank": ("d_phase2_scenarios.json", "Run Generate first"),
    "rerank_a": ("a1_phase3_scenarios.json", "No A1 data yet"),
    "rerank_c": ("c_phase2_scenarios.json", "No C data yet"),
    "rerank_d": ("d_phase2_scenarios.json", "No D data yet"),
}
IMPACT = {
    "a1_cluster_generate": ("Replaces A1 clusters + scenarios.", "Re-run A1 Re-rank and D afterward."),
    "rerank_a": ("Replaces A1 final results.", ""),
    "b_select": ("Replaces signal selection.", "Re-run Dedup afterward."),
    "b_dedup": ("Replaces deduplicated signals.", "Re-run C if you want updated results."),
    "c_cluster": ("Replaces signal groupings.", "Re-run C Generate and Rank afterward."),
    "c_generate": ("Replaces generated scenarios.", "Re-run C Rank afterward."),
    "c_rank": ("Replaces C final results.", "Re-run D for updated opportunities."),
    "d_pair": ("Replaces pair selection.", "Re-run D Generate and Rank afterward."),
    "d_generate": ("Replaces generated opportunities.", "Re-run D Rank afterward."),
    "d_rank": ("Replaces D final results.", ""),
    "rerank_c": ("Replaces C final results.", ""), "rerank_d": ("Replaces D final results.", ""),
}
STEPS = {
    "A1": {"icon": "article", "title": "Expected Scenarios",
           "sub": "Structural changes from news data",
           "check": "a1_phase3_scenarios.json", "output": "A1_expected_scenarios_ja.json", "depends": None},
    "B":  {"icon": "sensors", "title": "Weak Signals",
           "sub": "Score, rank, and filter signals",
           "check": "b_phase3_dedup_selected.json", "output": "B_selected_weak_signals_ja.json", "depends": None},
    "C":  {"icon": "bolt", "title": "Unexpected Scenarios",
           "sub": "Surprising futures from weak signals",
           "check": "c_phase2_scenarios.json", "output": "C_unexpected_scenarios_ja.json", "depends": "B"},
    "D":  {"icon": "lightbulb", "title": "Opportunities",
           "sub": "Business opportunities from A1 × C",
           "check": "d_phase2_scenarios.json", "output": "D_opportunity_scenarios_ja.json", "depends": "A1+C"},
}


def get_status(code):
    from utils.data_io import read_json
    info = STEPS[code]
    for key, label in [(info["output"], "delivered"), (info["check"], "candidates")]:
        p = (cfg.OUTPUT_DIR if key == info["output"] else cfg.INTERMEDIATE_DIR) / key
        if p.exists():
            d = read_json(p)
            if d:
                return "done", f"{len(d)} {label}", datetime.fromtimestamp(p.stat().st_mtime).strftime("%m/%d %H:%M")
    return "pending", "Not started", ""


def can_run(key):
    if key not in DEPS:
        return True, ""
    f, m = DEPS[key]
    return (cfg.INTERMEDIATE_DIR / f).exists(), m


def build_summary(key):
    try:
        from utils.data_io import read_json
        fmap = {
            "a1_cluster_generate": ("a1_phase3_scenarios.json", "scenarios generated", "title_ja"),
            "b_select": ("b_phase2_top3000_candidates.json", "signals selected", "title_ja"),
            "b_dedup": ("b_phase3_dedup_selected.json", "signals after dedup", "title_ja"),
            "c_cluster": ("c_phase1_clusters.json", "groups created", "theme_ja"),
            "c_generate": ("c_phase2_scenarios.json", "scenarios generated", "title_ja"),
            "d_pair": ("d_phase1_pairs.json", "pairs created", None),
            "d_generate": ("d_phase2_scenarios.json", "scenarios generated", "opportunity_title_ja"),
        }
        omap = {
            "c_rank": ("C_unexpected_scenarios_ja.json", "title_ja"),
            "d_rank": ("D_opportunity_scenarios_ja.json", "opportunity_title_ja"),
            "rerank_a": ("A1_expected_scenarios_ja.json", "title_ja"),
            "rerank_c": ("C_unexpected_scenarios_ja.json", "title_ja"),
            "rerank_d": ("D_opportunity_scenarios_ja.json", "opportunity_title_ja"),
        }
        if key in fmap:
            fn, lbl, tk = fmap[key]
            d = read_json(cfg.INTERMEDIATE_DIR / fn)
            pv = [it.get(tk, "")[:40] for it in d[:3] if tk and it.get(tk)] if tk else []
            return {"count": len(d), "label": lbl, "previews": pv}
        if key in omap:
            fn, tk = omap[key]
            p = cfg.OUTPUT_DIR / fn
            if p.exists():
                d = read_json(p)
                return {"count": len(d), "label": "passed all filters",
                        "previews": [it.get(tk, "")[:40] for it in d[:3] if it.get(tk)]}
    except Exception:
        pass
    return None


class LogHandler(logging.Handler):
    def emit(self, record):
        state["logs"].append(self.format(record))
        if len(state["logs"]) > 300:
            state["logs"] = state["logs"][-300:]


async def execute(key, ov, status_el, ind, log_area, sbox, pbar):
    if state["running"]:
        ui.notify("Already running.", type="warning"); return
    ok, msg = can_run(key)
    if not ok:
        ui.notify(msg, type="negative"); return
    state.update(running=True, step=key, logs=[], last_summary=None)
    apply_overrides(ov)
    lbl = LABELS.get(key, key)
    status_el.text = f"Running {lbl}..."
    status_el.classes(replace="text-amber-600 text-xs font-medium")
    ind.visible = True; pbar.visible = True
    log_area.clear()
    sbox.clear()
    with sbox:
        with ui.row().classes("items-center gap-2 py-2"):
            ui.spinner("dots", size="xs"); ui.label(f"Running...").classes("text-xs text-gray-400")

    def _run():
        try:
            if key == "a1_cluster_generate":
                from steps.step_a1 import phase2_cluster, phase3_generate; phase3_generate(phase2_cluster())
            elif key == "rerank_a": from rerank import rerank_a; rerank_a()
            elif key == "b_select": from steps.step_b import select_top_signals; select_top_signals()
            elif key == "b_dedup": from steps.step_b import diversity_dedup; diversity_dedup()
            elif key == "c_cluster":
                from steps.step_c import phase1_cluster, phase1_random
                (phase1_random if cfg.C_MODE == "random" else phase1_cluster)()
            elif key == "c_generate": from steps.step_c import phase2_generate; phase2_generate()
            elif key == "c_rank": from steps.step_c import phase3_rank; phase3_rank()
            elif key == "rerank_c": from rerank import rerank_c; rerank_c()
            elif key == "d_pair":
                from steps.step_d import phase1_select_pairs, phase1_random_pairs
                (phase1_random_pairs if cfg.D_MODE == "random" else phase1_select_pairs)()
            elif key == "d_generate": from steps.step_d import phase2_generate; phase2_generate()
            elif key == "d_rank": from steps.step_d import phase3_rank; phase3_rank()
            elif key == "rerank_d": from rerank import rerank_d; rerank_d()
            state["last_summary"] = build_summary(key)
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            state["last_summary"] = {"error": str(e)}
        finally:
            state.update(running=False, last_run=datetime.now().strftime("%H:%M"))
    await asyncio.get_event_loop().run_in_executor(None, _run)


# ─── Design System ──────────────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
* { font-family: 'Inter', -apple-system, sans-serif !important; }
body { background: #fafafa; }
.c { border: 1px solid #e5e7eb; border-radius: 12px; background: white; padding: 20px; }
.c-flush { border: 1px solid #e5e7eb; border-radius: 12px; background: white; }
.c:hover { border-color: #d1d5db; }
.tag { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px;
       border-radius: 99px; font-size: 11px; font-weight: 500; }
.tag-done { background: #ecfdf5; color: #059669; }
.tag-wait { background: #f3f4f6; color: #6b7280; }
.tag-run { background: #fffbeb; color: #d97706; }
.est { color: #9ca3af; font-size: 11px; }
.section-label { font-size: 11px; font-weight: 600; letter-spacing: 0.05em;
                  text-transform: uppercase; color: #9ca3af; margin-bottom: 12px; }
.hint { font-size: 11px; color: #9ca3af; line-height: 1.4; }
.info-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
            padding: 10px 14px; font-size: 12px; color: #64748b; }
.warn-box { background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px;
            padding: 10px 14px; }
.ok-box { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 12px 16px; }
.err-box { background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 12px 16px; }
.hero { background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
        border-radius: 16px; color: white; padding: 36px; }
</style>
"""


def settings_ui(section, p, show_adv=True):
    items = [(k, v) for k, v in UI_PARAMS.items() if v["section"] == section]
    main = [(k, v) for k, v in items if v.get("priority") == "main"]
    adv = [(k, v) for k, v in items if v.get("priority") == "advanced"]

    def _f(k, s):
        d = s["default"]; p.setdefault(k, d); h = s.get("hint", "")
        if s["type"] == "number":
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(s["label"]).classes("text-sm text-gray-600")
                n = ui.number(value=d, min=s.get("min", 0), max=s.get("max", 100)).classes("w-20").props("dense borderless")
                n.on_value_change(lambda e, k=k: p.update({k: e.value}))
            if h: ui.label(h).classes("hint -mt-1")
        elif s["type"] == "bool":
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label(s["label"]).classes("text-sm text-gray-600")
                    if h: ui.label(h).classes("hint")
                sw = ui.switch(value=d).props("dense color=indigo")
                sw.on_value_change(lambda e, k=k: p.update({k: e.value}))
        elif s["type"] == "select":
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(s["label"]).classes("text-sm text-gray-600")
                sl = ui.select(s["options"], value=d).classes("w-36").props("dense borderless")
                sl.on_value_change(lambda e, k=k: p.update({k: e.value}))
            if h: ui.label(h).classes("hint -mt-1")
        elif s["type"] == "text":
            ui.input(label=s["label"], value=str(d)).classes("w-full").props("dense borderless")
            if h: ui.label(h).classes("hint")

    for k, s in main:
        _f(k, s)
        ui.separator().classes("my-1 opacity-30")
    if adv and show_adv:
        with ui.expansion("Advanced filters", icon="tune").classes("w-full text-xs text-gray-400").props("dense"):
            for k, s in adv:
                _f(k, s)


# ─── Page ───────────────────────────────────────────
@ui.page("/")
def page():
    ui.add_head_html(CSS)
    P = {}; lr = [None]; sr = [None]

    # Header
    with ui.row().classes("w-full bg-white border-b border-gray-100 px-6 py-2.5 items-center justify-between"):
        with ui.row().classes("items-center gap-2"):
            ui.label("JRI").classes("text-sm font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded")
            ui.label("Living Lab+ Pipeline").classes("text-sm font-semibold text-gray-700")
        with ui.row().classes("items-center gap-3"):
            ind = ui.spinner("dots", size="xs", color="amber"); ind.visible = False
            st_el = ui.label("Ready").classes("text-xs font-medium text-emerald-600")
    pbar = ui.linear_progress(show_value=False).classes("w-full").props("indeterminate color=amber size=2px")
    pbar.visible = False

    # Tabs
    with ui.tabs().classes("w-full bg-white border-b border-gray-100 px-4").props(
        "active-color=indigo indicator-color=indigo dense no-caps align=left inline-label"
    ) as tabs:
        t0 = ui.tab("dash", label="Dashboard", icon="space_dashboard")
        t1 = ui.tab("a1", label="A1 Expected", icon="article")
        t2 = ui.tab("b", label="B Signals", icon="sensors")
        t3 = ui.tab("c", label="C Unexpected", icon="bolt")
        t4 = ui.tab("d", label="D Opportunity", icon="lightbulb")
        t5 = ui.tab("out", label="Results", icon="download")

    with ui.tab_panels(tabs, value=t0).classes("w-full bg-transparent"):

        # ── DASHBOARD ───────────────────
        with ui.tab_panel(t0):
            with ui.column().classes("w-full max-w-3xl mx-auto py-8 gap-6"):
                # Hero
                with ui.element("div").classes("hero"):
                    ui.label("Scenario Analysis").classes("text-2xl font-bold mb-1")
                    ui.label("Generate foresight reports in 4 steps. Configure, run, download.").classes("text-sm opacity-70 mb-5")
                    ui.button("Start with A1  →", on_click=lambda: tabs.set_value("a1")).props(
                        "unelevated color=white text-color=indigo no-caps size=sm"
                    )

                # Status
                with ui.element("div").classes("c"):
                    ui.label("PIPELINE STATUS").classes("section-label")
                    sc = ui.column().classes("w-full gap-0")

                    def refresh_dash():
                        sc.clear()
                        with sc:
                            for i, (code, info) in enumerate(STEPS.items()):
                                s, det, tm = get_status(code)
                                with ui.row().classes(
                                    "w-full items-center py-3 cursor-pointer hover:bg-gray-50 -mx-2 px-2 rounded-lg"
                                ).on("click", lambda c=code: tabs.set_value(c.lower() if len(c) == 1 else "a1")):
                                    ui.icon(info["icon"], size="xs").classes("text-gray-400 w-6")
                                    with ui.column().classes("flex-grow gap-0"):
                                        ui.label(f"{code}  {info['title']}").classes("text-sm font-medium text-gray-800")
                                        sub = info["sub"]
                                        if info["depends"]:
                                            sub += f"  ·  requires {info['depends']}"
                                        ui.label(sub).classes("text-xs text-gray-400")
                                    if s == "done":
                                        with ui.element("div").classes("tag tag-done"):
                                            ui.label(det)
                                        ui.label(tm).classes("text-xs text-gray-300 w-16 text-right")
                                    else:
                                        with ui.element("div").classes("tag tag-wait"):
                                            ui.label(det)
                                    ui.icon("chevron_right", size="xs").classes("text-gray-300")
                                if i < len(STEPS) - 1:
                                    ui.separator().classes("opacity-30")

                    refresh_dash()
                    ui.button("Refresh", icon="refresh", on_click=refresh_dash).props("flat dense size=xs color=grey no-caps").classes("mt-2")

                # Data + Global side by side
                with ui.row().classes("w-full gap-4"):
                    with ui.element("div").classes("c flex-1"):
                        ui.label("DATA").classes("section-label")
                        for f in [cfg.A1_INPUT_FILE, cfg.B_INPUT_FILE]:
                            with ui.row().classes("items-center gap-2 py-1"):
                                ui.icon("description", size="xs").classes("text-gray-300")
                                ui.label(f.name).classes("text-xs text-gray-500 font-mono")
                        ui.element("div").classes("info-box mt-3").text = (
                            "Changing the Research Topic adjusts AI focus but uses the same dataset. "
                            "To analyze a different topic, upload new data."
                        )
                        # Fix: use ui.html instead
                    with ui.element("div").classes("c flex-1"):
                        ui.label("GLOBAL SETTINGS").classes("section-label")
                        settings_ui("Global", P, show_adv=False)

                # Quick help
                with ui.element("div").classes("c"):
                    with ui.expansion("What does each step produce?", icon="help_outline").classes("w-full text-sm text-gray-500").props("dense"):
                        for code, info in STEPS.items():
                            with ui.row().classes("py-1"):
                                ui.label(f"{code}").classes("text-xs font-bold text-gray-400 w-8")
                                ui.label(f"{info['title']} — {info['sub']}").classes("text-xs text-gray-500")

        # ── STEP TAB BUILDER ────────────
        def step_tab(panel, code, phases, lock_msg, section, actions, extra=None):
            info = STEPS[code]
            with ui.tab_panel(panel):
                with ui.column().classes("w-full max-w-3xl mx-auto py-6 gap-5"):

                    # Header
                    s, det, tm = get_status(code)
                    with ui.row().classes("items-center justify-between"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon(info["icon"], size="sm").classes("text-gray-400")
                            with ui.column().classes("gap-0"):
                                ui.label(f"Step {code}").classes("text-lg font-semibold text-gray-800")
                                ui.label(info["sub"]).classes("text-xs text-gray-400")
                        with ui.column().classes("items-end gap-0"):
                            tag_cls = "tag-done" if s == "done" else "tag-wait"
                            with ui.element("div").classes(f"tag {tag_cls}"):
                                ui.label(det)
                            if tm:
                                ui.label(tm).classes("text-xs text-gray-300")

                    # Extra (e.g. mode comparison)
                    if extra:
                        extra()

                    # Two columns: process + settings
                    with ui.row().classes("w-full gap-4 items-start"):
                        with ui.element("div").classes("c flex-1"):
                            ui.label("PROCESS").classes("section-label")
                            for i, (txt, locked) in enumerate(phases):
                                with ui.row().classes("items-center gap-3 py-1.5"):
                                    if locked:
                                        ui.icon("lock", size="xs").classes("text-gray-200")
                                    else:
                                        ui.label(str(i + 1)).classes("text-xs font-bold text-gray-300 w-4 text-center")
                                    ui.label(txt).classes(f"text-sm {'text-gray-300' if locked else 'text-gray-600'}")
                            if lock_msg:
                                with ui.element("div").classes("info-box mt-3"):
                                    ui.label(lock_msg).classes("text-xs")

                        with ui.element("div").classes("c flex-1"):
                            ui.label("SETTINGS").classes("section-label")
                            settings_ui(section, P)

                    # Actions
                    with ui.element("div").classes("c"):
                        ui.label("RUN").classes("section-label")
                        sbox = ui.column().classes("w-full"); sr[0] = sbox
                        btns = []
                        with ui.row().classes("gap-3 flex-wrap items-start"):
                            for i, (lbl, icn, key, outline, est) in enumerate(actions):
                                ok, dm = can_run(key)
                                with ui.column().classes("gap-1"):
                                    async def _click(k=key, sb=sbox):
                                        if k not in ("b_select",):
                                            rep, down = IMPACT.get(k, ("", ""))
                                            with ui.dialog() as dlg, ui.card().classes("p-5 max-w-sm"):
                                                ui.label(LABELS.get(k, k)).classes("text-base font-semibold mb-3")
                                                with ui.row().classes("items-center gap-2"):
                                                    ui.icon("schedule", size="xs").classes("text-gray-300")
                                                    ui.label(EST.get(k, "")).classes("text-xs text-gray-400")
                                                ui.label("API cost is charged per run.").classes("text-xs text-gray-300 mt-1")
                                                if rep:
                                                    with ui.element("div").classes("warn-box mt-3"):
                                                        ui.label(rep).classes("text-xs text-amber-700")
                                                        if down:
                                                            ui.label(down).classes("text-xs text-amber-500 mt-1")
                                                with ui.row().classes("mt-4 gap-2 justify-end"):
                                                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps size=sm")
                                                    ui.button("Run", icon="play_arrow",
                                                        on_click=lambda d=dlg: (d.close(), None) or asyncio.ensure_future(
                                                            execute(k, P, st_el, ind, lr[0] or ui.log(), sb, pbar)
                                                        )
                                                    ).props("unelevated no-caps size=sm color=indigo")
                                            dlg.open()
                                        else:
                                            await execute(k, P, st_el, ind, lr[0] or ui.log(), sb, pbar)

                                    num = f"{i+1}. " if len(actions) > 1 else ""
                                    props = "no-caps size=sm"
                                    if outline:
                                        props += " outline color=indigo"
                                    else:
                                        props += " unelevated color=indigo"
                                    if not ok:
                                        props += " disable"
                                    b = ui.button(f"{num}{lbl}", icon=icn, on_click=_click).props(props)
                                    if not ok:
                                        b.tooltip(dm)
                                    btns.append((b, key))
                                    ui.label(est).classes("est")

                    # Log
                    with ui.expansion("Log", icon="terminal").classes("w-full text-xs text-gray-400").props("dense"):
                        la = ui.log(max_lines=100).classes("w-full h-32 bg-gray-950 text-emerald-400 rounded-lg text-xs font-mono")
                        if not lr[0]: lr[0] = la

                        def tick(a=la, sb=sbox, bs=btns):
                            for l in state["logs"]: a.push(l)
                            state["logs"] = []
                            if not state["running"] and state.get("last_run"):
                                st_el.text = f"Done ({state['last_run']})"
                                st_el.classes(replace="text-xs font-medium text-emerald-600")
                                ind.visible = False; pbar.visible = False
                                for b, k in bs:
                                    ok, _ = can_run(k)
                                    b.props(remove="disable") if ok else b.props(add="disable")
                                sm = state.get("last_summary")
                                if sm and sb:
                                    sb.clear()
                                    with sb:
                                        if "error" in sm:
                                            with ui.element("div").classes("err-box"):
                                                ui.label(f"Error: {sm['error'][:120]}").classes("text-xs text-red-600")
                                        elif "count" in sm:
                                            with ui.element("div").classes("ok-box"):
                                                with ui.row().classes("items-center gap-2"):
                                                    ui.icon("check_circle", size="xs").classes("text-emerald-500")
                                                    ui.label(f"{sm['count']} {sm['label']}").classes("text-sm font-medium text-emerald-700")
                                                for pv in sm.get("previews", []):
                                                    ui.label(f"  → {pv}").classes("text-xs text-gray-500 ml-5")
                                    state["last_summary"] = None
                        ui.timer(1.0, tick)

                    # Next
                    nx = {"A1": ("b", "B Signals"), "B": ("c", "C Unexpected"),
                          "C": ("d", "D Opportunity"), "D": ("out", "Results")}
                    if code in nx:
                        tk, nl = nx[code]
                        with ui.row().classes("w-full justify-end"):
                            ui.button(f"Next: {nl} →", on_click=lambda t=tk: tabs.set_value(t)).props("flat no-caps size=sm color=indigo")

        # ── A1 ──
        step_tab(t1, "A1",
            [("Summarize articles", True), ("Cluster into themes", False),
             ("Generate scenarios", False), ("Score and filter", False)],
            "Summarization is pre-computed. Start from clustering.",
            "A1 Expected",
            [("Cluster + Generate", "hub", "a1_cluster_generate", False, EST["a1_cluster_generate"]),
             ("Re-rank only", "sort", "rerank_a", True, EST["rerank_a"])])

        # ── B ──
        step_tab(t2, "B",
            [("Score all signals", True), ("Apply thresholds, select top N", False),
             ("Remove near-duplicates", False)],
            "Scoring is pre-computed. Adjust thresholds and re-select.",
            "B Weak Signal",
            [("Select Top N", "filter_alt", "b_select", False, EST["b_select"]),
             ("Diversity dedup", "content_cut", "b_dedup", True, EST["b_dedup"])])

        # ── C ──
        def c_extra():
            with ui.element("div").classes("c"):
                ui.label("MODE COMPARISON").classes("section-label")
                with ui.row().classes("gap-3"):
                    with ui.element("div").classes("flex-1 p-3 rounded-lg bg-gray-50 border border-gray-200"):
                        ui.label("Cluster").classes("text-sm font-semibold text-gray-700 mb-1")
                        ui.label("Groups similar signals. Ensures comprehensive coverage.").classes("text-xs text-gray-400")
                        ui.label("+ Consistent · + Complete coverage").classes("text-xs text-emerald-500 mt-2")
                        ui.label("− May miss cross-domain leaps").classes("text-xs text-orange-400")
                    with ui.element("div").classes("flex-1 p-3 rounded-lg bg-gray-50 border border-gray-200"):
                        ui.label("Random").classes("text-sm font-semibold text-gray-700 mb-1")
                        ui.label("Randomly mixes signals for unexpected combinations.").classes("text-xs text-gray-400")
                        ui.label("+ Creative leaps · + Different each run").classes("text-xs text-emerald-500 mt-2")
                        ui.label("− Some combos may not produce useful results").classes("text-xs text-orange-400")

        step_tab(t3, "C",
            [("Group signals (cluster or random)", False),
             ("Generate unexpected scenarios", False), ("Score and filter", False)],
            None, "C Unexpected",
            [("Group signals", "hub", "c_cluster", False, EST["c_cluster"]),
             ("Generate", "auto_awesome", "c_generate", True, EST["c_generate"]),
             ("Rank & filter", "sort", "c_rank", True, EST["c_rank"])],
            extra=c_extra)

        # ── D ──
        step_tab(t4, "D",
            [("Select A1 × C pairs", False), ("Generate opportunity scenarios", False),
             ("Score, filter, classify", False)],
            None, "D Opportunity",
            [("Create pairs", "shuffle", "d_pair", False, EST["d_pair"]),
             ("Generate", "auto_awesome", "d_generate", True, EST["d_generate"]),
             ("Rank & classify", "sort", "d_rank", True, EST["d_rank"])])

        # ── RESULTS ─────────────────────
        with ui.tab_panel(t5):
            with ui.column().classes("w-full max-w-3xl mx-auto py-6 gap-5"):
                ui.label("Results").classes("text-lg font-semibold text-gray-800")
                ui.label("Download your generated reports.").classes("text-xs text-gray-400 -mt-3 mb-2")

                rbox = ui.column().classes("w-full gap-3")
                show_all = {"v": False}

                def rf():
                    rbox.clear()
                    od = cfg.OUTPUT_DIR
                    fs = []
                    if od.exists():
                        if show_all["v"]:
                            fs = [f for f in sorted(od.iterdir()) if f.suffix in (".pptx", ".xlsx", ".json")]
                        else:
                            fs = [f for f in sorted(od.iterdir()) if f.suffix in (".pptx", ".xlsx")]
                    if not fs:
                        with rbox:
                            with ui.column().classes("w-full items-center py-16"):
                                ui.icon("inbox", size="2rem").classes("text-gray-200 mb-2")
                                ui.label("No reports yet").classes("text-sm text-gray-400")
                        return
                    pptx = [f for f in fs if f.suffix == ".pptx"]
                    other = [f for f in fs if f.suffix != ".pptx"]
                    with rbox:
                        if pptx:
                            with ui.element("div").classes("c"):
                                ui.label("REPORTS").classes("section-label")
                                for f in pptx:
                                    kb = f.stat().st_size / 1024
                                    with ui.row().classes("w-full items-center py-2"):
                                        ui.icon("slideshow", size="xs").classes("text-red-400")
                                        ui.label(f.name).classes("text-sm text-gray-700 flex-grow")
                                        ui.label(f"{kb:,.0f} KB").classes("text-xs text-gray-300")
                                        ui.button("Download", icon="download",
                                            on_click=lambda p=f: ui.download(str(p))
                                        ).props("unelevated no-caps size=sm color=red")
                        if other:
                            with ui.element("div").classes("c"):
                                ui.label("DATA FILES").classes("section-label")
                                for f in other:
                                    kb = f.stat().st_size / 1024
                                    ext = f.suffix[1:].upper()
                                    with ui.row().classes("w-full items-center py-1.5"):
                                        ui.label(ext).classes("text-xs font-mono text-gray-300 w-10")
                                        ui.label(f.name).classes("text-xs text-gray-500 font-mono flex-grow")
                                        ui.label(f"{kb:,.0f} KB").classes("text-xs text-gray-300")
                                        ui.button(icon="download",
                                            on_click=lambda p=f: ui.download(str(p))
                                        ).props("flat round size=xs color=grey")

                with ui.row().classes("gap-2"):
                    ui.button("Refresh", icon="refresh", on_click=rf).props("flat no-caps size=xs color=grey")
                    def _toggle():
                        show_all["v"] = not show_all["v"]; rf()
                    ui.button("Show all files" if not show_all["v"] else "Reports only",
                        icon="visibility", on_click=_toggle).props("flat no-caps size=xs color=grey")
                rf()

    h = LogHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(h)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="JRI Pipeline", port=8080, reload=False)
