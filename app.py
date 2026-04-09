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
# Set credentials via environment variables or defaults
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
         "last_summary": None, "phase": "", "phase_num": 0, "phase_total": 0}

LABELS = {
    "run_a1": "Step A1", "run_b": "Step B", "run_c": "Step C", "run_d": "Step D",
    "b_select": "B Preview",
    "c_cluster": "C Regroup",
}
EST_TIME = {
    "b_select": "instant · free",
    "c_cluster": "~1-2 min · ~$1",
}
ACTION_IMPACT = {
    "run_a1": ("Replaces all A1 results.", "Re-run D afterward for updated opportunities."),
    "run_b": ("Replaces signal selection.", "Re-run C and D afterward."),
    "run_c": ("Replaces all C results.", "Re-run D afterward for updated opportunities."),
    "run_d": ("Replaces all D results.", ""),
    "b_select": ("Replaces signal selection.", ""),
    "c_cluster": ("Replaces signal groupings only.", "Run Step C for full results."),
}
STEPS = {
    "A1": {"icon": "article", "title": "Expected Scenarios",
           "sub": "Structural changes from news articles",
           "output": "A1_expected_scenarios_ja.json", "check": "a1_phase3_scenarios.json"},
    "B":  {"icon": "sensors", "title": "Weak Signals",
           "sub": "Scored and filtered signals",
           "output": "B_selected_weak_signals_ja.json", "check": "b_phase3_dedup_selected.json"},
    "C":  {"icon": "bolt", "title": "Unexpected Scenarios",
           "sub": "Surprising futures from signals",
           "output": "C_unexpected_scenarios_ja.json", "check": "c_phase2_scenarios.json"},
    "D":  {"icon": "lightbulb", "title": "Opportunities",
           "sub": "Business opportunities from A1 × C",
           "output": "D_opportunity_scenarios_ja.json", "check": "d_phase2_scenarios.json"},
}


def get_status(code):
    from utils.data_io import read_json
    info = STEPS[code]
    for key, label in [(info["output"], "delivered"), (info["check"], "candidates")]:
        d = (cfg.OUTPUT_DIR if key == info["output"] else cfg.INTERMEDIATE_DIR)
        p = d / key
        if p.exists():
            data = read_json(p)
            if data:
                t = datetime.fromtimestamp(p.stat().st_mtime).strftime("%m/%d %H:%M")
                return "done", f"{len(data)} {label}", t
    return "pending", "Not started", ""


def est_full(key, params):
    a1 = params.get("A1_GENERATE_N", 20) or 20
    c = params.get("C_GENERATE_N", 150) or 150
    d = params.get("D_GENERATE_N", 40) or 40
    m = {"run_a1": max(3, int(a1*0.5)), "run_b": 4, "run_c": max(3, int(c*0.1)), "run_d": max(3, int(d*0.3))}
    cost = {"run_a1": max(1, round(a1*0.25)), "run_b": 1, "run_c": max(1, round(c*0.06)), "run_d": max(1, round(d*0.15))}
    if key in m:
        return f"~{m[key]} min · ~${cost[key]}"
    return EST_TIME.get(key, "")


def build_summary(step_key):
    try:
        from utils.data_io import read_json
        omap = {
            "run_a1": ("A1_expected_scenarios_ja.json", "scenarios delivered", "title_ja"),
            "run_b": ("B_selected_weak_signals_ja.json", "signals selected", "title_ja"),
            "run_c": ("C_unexpected_scenarios_ja.json", "scenarios delivered", "title_ja"),
            "run_d": ("D_opportunity_scenarios_ja.json", "opportunities delivered", "opportunity_title_ja"),
            "b_select": ("b_phase2_top3000_candidates.json", "signals selected", "title_ja"),
            "c_cluster": ("c_phase1_clusters.json", "groups created", "theme_ja"),
        }
        if step_key in omap:
            fn, lbl, tk = omap[step_key]
            d = cfg.OUTPUT_DIR if step_key.startswith("run_") else cfg.INTERMEDIATE_DIR
            p = d / fn
            if p.exists():
                data = read_json(p)
                pv = [it.get(tk, "")[:40] for it in data[:3] if tk and it.get(tk)]
                return {"count": len(data), "label": lbl, "previews": pv}
    except Exception:
        pass
    return None


class LogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        # Strip local paths from log output
        msg = msg.replace(str(cfg.BASE_DIR) + "/", "").replace(str(cfg.BASE_DIR), "")
        state["logs"].append(msg)
        if len(state["logs"]) > 300:
            state["logs"] = state["logs"][-300:]


async def run_step(key, ov, ui_refs):
    if state["running"]:
        ui.notify("Already running.", type="warning"); return
    state.update(running=True, step=key, logs=[], last_summary=None, phase="Starting...", phase_num=0, phase_total=0)
    apply_overrides(ov)
    ui_refs["status"].text = f"Running..."
    ui_refs["status"].classes(replace="text-amber-600 text-xs font-medium")
    ui_refs["indicator"].visible = True
    ui_refs["pbar"].visible = True

    def _run():
        def _p(name, n, t):
            state.update(phase=name, phase_num=n, phase_total=t)
        try:
            if key == "run_a1":
                from steps.step_a1 import phase2_cluster, phase3_generate, phase4_rank
                _p("Clustering articles...", 1, 3); themes = phase2_cluster()
                _p("Generating scenarios...", 2, 3); scenarios = phase3_generate(themes)
                _p("Scoring & filtering...", 3, 3); phase4_rank(scenarios)
            elif key == "run_b":
                from steps.step_b import select_top_signals, diversity_dedup
                _p("Selecting signals...", 1, 2); cands = select_top_signals()
                _p("Removing duplicates...", 2, 2); diversity_dedup(cands)
            elif key == "run_c":
                from steps.step_c import phase1_cluster, phase1_random, phase2_generate, phase3_rank
                _p("Grouping signals...", 1, 3)
                cl = (phase1_random if cfg.C_MODE == "random" else phase1_cluster)()
                _p("Generating scenarios...", 2, 3); sc = phase2_generate(cl)
                _p("Scoring & filtering...", 3, 3); phase3_rank(sc)
            elif key == "run_d":
                from steps.step_d import phase1_select_pairs, phase1_random_pairs, phase2_generate, phase3_rank
                from utils.data_io import read_json
                exp = read_json(cfg.OUTPUT_DIR / "A1_expected_scenarios_ja.json")
                unexp = read_json(cfg.OUTPUT_DIR / "C_unexpected_scenarios_ja.json")
                _p("Pairing scenarios...", 1, 3)
                pairs = (phase1_random_pairs if cfg.D_MODE == "random" else phase1_select_pairs)(exp, unexp)
                _p("Generating opportunities...", 2, 3); sc = phase2_generate(pairs, exp, unexp)
                _p("Scoring & classifying...", 3, 3); phase3_rank(sc)
            elif key == "b_select":
                from steps.step_b import select_top_signals; select_top_signals()
            elif key == "c_cluster":
                from steps.step_c import phase1_cluster, phase1_random
                (phase1_random if cfg.C_MODE == "random" else phase1_cluster)()
            state["last_summary"] = build_summary(key)
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            state["last_summary"] = {"error": str(e)}
        finally:
            state.update(running=False, last_run=datetime.now().strftime("%H:%M"))
    await asyncio.get_event_loop().run_in_executor(None, _run)


def render_params(section, P):
    items = [(k, v) for k, v in UI_PARAMS.items() if v["section"] == section]
    main = [(k, v) for k, v in items if v.get("priority") == "main"]
    adv = [(k, v) for k, v in items if v.get("priority") == "advanced"]

    def _f(k, s):
        d = s["default"]; P.setdefault(k, d); h = s.get("hint", "")
        if s["type"] == "number":
            with ui.row().classes("w-full items-center justify-between py-1"):
                ui.label(s["label"]).classes("text-sm text-gray-600")
                n = ui.number(value=d, min=s.get("min",0), max=s.get("max",100)).classes("w-24").props("dense outlined")
                n.on_value_change(lambda e, k=k: P.update({k: e.value}))
            if h: ui.label(h).classes("text-xs text-gray-400 -mt-1")
        elif s["type"] == "bool":
            with ui.row().classes("w-full items-center justify-between py-1"):
                ui.label(s["label"]).classes("text-sm text-gray-600")
                sw = ui.switch(value=d).props("dense")
                sw.on_value_change(lambda e, k=k: P.update({k: e.value}))
            if h: ui.label(h).classes("text-xs text-gray-400")
        elif s["type"] == "select":
            with ui.row().classes("w-full items-center justify-between py-1"):
                ui.label(s["label"]).classes("text-sm text-gray-600")
                sl = ui.select(s["options"], value=d).classes("w-40").props("dense outlined")
                sl.on_value_change(lambda e, k=k: P.update({k: e.value}))
            if h: ui.label(h).classes("text-xs text-gray-400 -mt-1")
        elif s["type"] == "text":
            ui.input(label=s["label"], value=str(d)).classes("w-full").props("dense outlined")
            if h: ui.label(h).classes("text-xs text-gray-400")

    for k, s in main:
        _f(k, s)
    if adv:
        with ui.expansion("Score filters", icon="tune").classes("w-full text-sm text-gray-400").props("dense"):
            for k, s in adv:
                _f(k, s)
            def _reset():
                for k, s in adv: P[k] = s["default"]
                ui.notify("Reset to defaults", type="info")
            ui.button("Reset to defaults", icon="restart_alt", on_click=_reset).props("flat size=sm color=grey").classes("mt-2")


# ─── Page ───────────────────────────────────────────

@ui.page("/")
def page():
    ui.add_head_html("""<style>
        body { background: #f7f8fa; }
        .card-s { border-radius: 14px !important; border: 1px solid #ebedf0 !important; box-shadow: none !important; }
        .card-s:hover { border-color: #dcdfe3 !important; }
        .q-tab { text-transform: none !important; font-size: 13px !important; }
        .q-btn { text-transform: none !important; }
        .progress-card { background: #fffbeb; border: 1px solid #fde68a; border-radius: 12px; padding: 16px; }
        .result-ok { background: #f0fdf4; border: 1px solid #d1fae5; border-radius: 12px; padding: 16px; }
        .result-err { background: #fef2f2; border: 1px solid #fee2e2; border-radius: 12px; padding: 16px; }
    </style>""")

    P = {}
    ui_refs = {}

    # Header
    with ui.column().classes("w-full gap-0"):
        with ui.row().classes("w-full bg-white border-b border-gray-100 px-6 py-2.5 items-center justify-between"):
            with ui.row().classes("items-center gap-2"):
                ui.label("JRI").classes("text-xs font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded")
                ui.label("Living Lab+ Pipeline").classes("text-sm font-semibold text-gray-700")
            with ui.row().classes("items-center gap-3"):
                ui_refs["indicator"] = ui.spinner("dots", size="xs", color="amber")
                ui_refs["indicator"].visible = False
                ui_refs["status"] = ui.label("Ready").classes("text-xs font-medium text-emerald-600")
                ui.separator().props("vertical").classes("h-4")
                def logout():
                    app.storage.user.clear()
                    ui.navigate.to("/login")
                ui.button(icon="logout", on_click=logout).props("flat round size=xs color=grey").tooltip("Sign out")
        ui_refs["pbar"] = ui.linear_progress(show_value=False).classes("w-full").props("indeterminate color=amber size=2px")
        ui_refs["pbar"].visible = False

    # Tabs
    with ui.tabs().classes("w-full bg-white border-b border-gray-100 px-4").props(
        "active-color=indigo indicator-color=indigo dense no-caps align=left"
    ) as tabs:
        t_setup = ui.tab("setup", label="Setup", icon="settings")
        t_a1 = ui.tab("a1", label="Expected", icon="article")
        t_b = ui.tab("b", label="Signals", icon="sensors")
        t_c = ui.tab("c", label="Unexpected", icon="bolt")
        t_d = ui.tab("d", label="Opportunities", icon="lightbulb")
        t_res = ui.tab("res", label="Results", icon="download")

    with ui.tab_panels(tabs, value=t_setup).classes("w-full flex-grow bg-transparent"):

        # ═══ SETUP ═══
        with ui.tab_panel(t_setup):
          with ui.scroll_area().classes("w-full"):
            with ui.column().classes("w-full max-w-3xl mx-auto py-6 gap-5"):
                ui.label("Setup").classes("text-xl font-semibold text-gray-800")
                ui.label("Configure your data and topic. Each step has its own settings.").classes("text-sm text-gray-400 -mt-3")

                # Data
                with ui.card().classes("w-full card-s p-5"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("cloud_upload", size="sm").classes("text-teal-500")
                        ui.label("Data").classes("font-semibold text-gray-700")
                    ui.label("Currently using pre-loaded datasets:").classes("text-xs text-gray-400 mb-2")
                    for f in [cfg.A1_INPUT_FILE, cfg.B_INPUT_FILE]:
                        with ui.row().classes("items-center gap-2 py-1"):
                            ui.icon("description", size="xs").classes("text-gray-300")
                            ui.label(f.name).classes("text-xs text-gray-500 font-mono")

                # Topic
                with ui.card().classes("w-full card-s p-5"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("public", size="sm").classes("text-blue-500")
                        ui.label("Topic & Industries").classes("font-semibold text-gray-700")
                    render_params("Global", P)

                # Pipeline Status
                with ui.card().classes("w-full card-s p-5"):
                    with ui.row().classes("items-center gap-2 mb-3"):
                        ui.icon("assessment", size="sm").classes("text-indigo-500")
                        ui.label("Pipeline Status").classes("font-semibold text-gray-700")
                    status_ctr = ui.column().classes("w-full gap-0")
                    def refresh_status():
                        status_ctr.clear()
                        with status_ctr:
                            for i, (code, info) in enumerate(STEPS.items()):
                                st, det, tm = get_status(code)
                                tab_key = code.lower() if len(code) == 1 else "a1"
                                with ui.row().classes("w-full items-center py-3 cursor-pointer hover:bg-gray-50 rounded-lg px-2").on(
                                    "click", lambda t=tab_key: tabs.set_value(t)
                                ):
                                    ui.icon(info["icon"], size="xs").classes("text-gray-400 w-6")
                                    ui.label(info["title"]).classes("text-sm text-gray-700 flex-grow")
                                    if st == "done":
                                        ui.badge(det, color="green").classes("text-xs")
                                        ui.label(tm).classes("text-xs text-gray-300 w-20 text-right")
                                    else:
                                        ui.badge("Not started", color="grey").classes("text-xs")
                                    ui.icon("chevron_right", size="xs").classes("text-gray-300")
                                if i < len(STEPS) - 1:
                                    ui.separator().classes("opacity-30")
                    refresh_status()
                    ui.button("Refresh", icon="refresh", on_click=refresh_status).props("flat no-caps size=sm color=grey").classes("mt-2")

        # ═══ STEP TABS ═══
        def step_tab(panel, code, run_key, section, note=None, extra=None):
            info = STEPS[code]
            with ui.tab_panel(panel):
                with ui.scroll_area().classes("w-full"):
                  with ui.column().classes("w-full max-w-3xl mx-auto py-6 gap-5"):
                    # Header
                    st, det, tm = get_status(code)
                    with ui.row().classes("w-full items-center justify-between"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon(info["icon"], size="sm").classes("text-gray-400")
                            with ui.column().classes("gap-0"):
                                ui.label(f"{info['title']}").classes("text-lg font-semibold text-gray-800")
                                ui.label(info["sub"]).classes("text-xs text-gray-400")
                        if st == "done":
                            with ui.column().classes("items-end gap-0"):
                                ui.badge(f"Done — {det}", color="green").classes("text-xs")
                                ui.label(tm).classes("text-xs text-gray-300 mt-0.5")
                        else:
                            ui.badge("Not started", color="grey").classes("text-xs")

                    if note:
                        with ui.row().classes("bg-amber-50 rounded-lg px-3 py-2 items-center gap-2"):
                            ui.icon("info", size="xs").classes("text-amber-500")
                            ui.label(note).classes("text-xs text-amber-700")

                    if extra:
                        extra()

                    # Settings for this step
                    with ui.card().classes("w-full card-s p-5"):
                        with ui.row().classes("items-center gap-2 mb-3"):
                            ui.icon("tune", size="sm").classes("text-gray-400")
                            ui.label("Settings").classes("font-semibold text-gray-700")
                        render_params(section, P)

                    # Run card
                    with ui.card().classes("w-full card-s p-5"):
                        status_box = ui.column().classes("w-full mb-3")

                        async def _click(k=run_key):
                            rep, down = ACTION_IMPACT.get(k, ("", ""))
                            with ui.dialog() as dlg, ui.card().classes("p-5 max-w-sm"):
                                ui.label(f"Run {info['title']}").classes("text-base font-semibold mb-2")
                                with ui.row().classes("items-center gap-2"):
                                    ui.icon("schedule", size="xs").classes("text-gray-400")
                                    ui.label(est_full(k, P)).classes("text-sm text-gray-400")
                                ui.label("API cost is charged per run.").classes("text-xs text-gray-300 mt-1")
                                if rep:
                                    ui.separator().classes("my-2")
                                    with ui.row().classes("items-start gap-2"):
                                        ui.icon("warning", size="xs").classes("text-orange-500 mt-0.5")
                                        with ui.column().classes("gap-0"):
                                            ui.label(rep).classes("text-xs text-orange-600")
                                            if down:
                                                ui.label(down).classes("text-xs text-orange-400 mt-1")
                                with ui.row().classes("mt-4 gap-2 justify-end"):
                                    ui.button("Cancel", on_click=dlg.close).props("flat no-caps size=sm")
                                    async def _confirmed(d=dlg, k=k):
                                        d.close()
                                        await run_step(k, P, ui_refs)
                                    ui.button("Run", icon="play_arrow",
                                        on_click=_confirmed
                                    ).props("unelevated no-caps size=sm color=indigo")
                            dlg.open()

                        ui.button(f"Run", icon="play_arrow", on_click=_click).props("color=indigo size=md")
                        ui.label(est_full(run_key, P)).classes("text-xs text-gray-400 mt-1")

                    # Log
                    with ui.expansion("Execution log", icon="terminal").classes("w-full text-xs text-gray-400").props("dense"):
                        la = ui.log(max_lines=80).classes("w-full h-32 bg-gray-950 text-emerald-400 rounded-lg text-xs font-mono")

                    # Tick
                    _prev_key = {"v": ""}

                    def tick(a=la, sb=status_box):
                        for l in state["logs"]: a.push(l)
                        state["logs"] = []

                        if state["running"]:
                            ph = state.get("phase", "")
                            pn = state.get("phase_num", 0)
                            pt = state.get("phase_total", 0)
                            key = f"r:{pn}:{ph}"
                            if key != _prev_key["v"]:
                                _prev_key["v"] = key
                                sb.clear()
                                with sb:
                                    with ui.card().classes("w-full bg-amber-50 border border-amber-200 p-4").style("border-radius:10px"):
                                        with ui.row().classes("items-center gap-3"):
                                            ui.spinner("dots", size="sm", color="amber")
                                            ui.label(f"Running...").classes("text-sm font-semibold text-amber-800")
                                        if pt > 0:
                                            ui.label(f"{pn}/{pt}: {ph}").classes("text-xs text-amber-600 mt-2")
                                            ui.linear_progress(value=pn/pt, show_value=False).classes("w-full mt-1").props("color=amber rounded size=8px")
                                        else:
                                            ui.label(ph or "Starting...").classes("text-xs text-amber-600 mt-1")

                        elif state.get("last_run"):
                            ui_refs["status"].text = f"Done ({state['last_run']})"
                            ui_refs["status"].classes(replace="text-xs font-medium text-emerald-600")
                            ui_refs["indicator"].visible = False
                            ui_refs["pbar"].visible = False
                            s = state.get("last_summary")
                            if s:
                                _prev_key["v"] = ""
                                sb.clear()
                                with sb:
                                    if "error" in s:
                                        with ui.column().classes("result-err"):
                                            with ui.row().classes("items-center gap-2"):
                                                ui.icon("error", size="sm").classes("text-red-500")
                                                ui.label(f"Error: {s['error'][:100]}").classes("text-sm text-red-600")
                                    elif "count" in s:
                                        with ui.column().classes("result-ok gap-1"):
                                            with ui.row().classes("items-center gap-2"):
                                                ui.icon("check_circle", size="sm").classes("text-green-500")
                                                ui.label(f"{s['count']} {s['label']}").classes("text-sm font-semibold text-green-700")
                                            for pv in s.get("previews", []):
                                                ui.label(f"→ {pv}").classes("text-xs text-gray-500 ml-5")
                                state["last_summary"] = None
                    ui.timer(1.0, tick)

                    # Next
                    nx = {"A1": ("b", "Weak Signals"), "B": ("c", "Unexpected Scenarios"),
                          "C": ("d", "Opportunities"), "D": ("res", "Results")}
                    if code in nx:
                        tk, nl = nx[code]
                        with ui.row().classes("w-full justify-end"):
                            ui.button(f"Next: {nl} →", on_click=lambda t=tk: tabs.set_value(t)).props("flat no-caps size=sm color=indigo")

        # A1
        step_tab(t_a1, "A1", "run_a1", "A1 Expected",
            "Article summarization is pre-computed. This re-runs clustering, generation, and scoring.")

        # B
        step_tab(t_b, "B", "run_b", "B Weak Signal",
            "Signal scoring is pre-computed. This re-runs selection and deduplication.")

        # C
        def c_mode_info():
            with ui.card().classes("w-full card-s p-4"):
                with ui.row().classes("w-full gap-4"):
                    with ui.card().classes("flex-1 bg-gray-50 p-3"):
                        ui.label("Cluster mode").classes("text-sm font-semibold text-gray-700 mb-1")
                        ui.label("Groups similar signals. Complete coverage, consistent results.").classes("text-xs text-gray-400")
                    with ui.card().classes("flex-1 bg-gray-50 p-3"):
                        ui.label("Random mode").classes("text-sm font-semibold text-gray-700 mb-1")
                        ui.label("Mixes signals randomly. Forces creative cross-domain leaps.").classes("text-xs text-gray-400")

        step_tab(t_c, "C", "run_c", "C Unexpected", extra=c_mode_info)

        # D
        step_tab(t_d, "D", "run_d", "D Opportunity")

        # ═══ RESULTS ═══
        with ui.tab_panel(t_res):
          with ui.scroll_area().classes("w-full"):
            with ui.column().classes("w-full max-w-3xl mx-auto py-6 gap-5"):
                ui.label("Results").classes("text-xl font-semibold text-gray-800")
                ui.label("Download your generated reports.").classes("text-sm text-gray-400 -mt-3")

                rbox = ui.column().classes("w-full gap-3")
                show_all = {"v": False}

                def refresh():
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
                            with ui.card().classes("w-full card-s p-5"):
                                ui.label("Reports").classes("text-sm font-semibold text-gray-600 mb-2")
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
                            with ui.card().classes("w-full card-s p-5"):
                                ui.label("Data files").classes("text-sm font-semibold text-gray-600 mb-2")
                                for f in other:
                                    kb = f.stat().st_size / 1024
                                    with ui.row().classes("w-full items-center py-1"):
                                        ui.label(f.suffix[1:].upper()).classes("text-xs text-gray-300 w-10 font-mono")
                                        ui.label(f.name).classes("text-xs text-gray-500 font-mono flex-grow")
                                        ui.label(f"{kb:,.0f} KB").classes("text-xs text-gray-300")
                                        ui.button(icon="download", on_click=lambda p=f: ui.download(str(p))).props("flat round size=xs color=grey")

                with ui.row().classes("gap-2"):
                    ui.button("Refresh", icon="refresh", on_click=refresh).props("flat no-caps size=sm color=grey")
                    def _toggle():
                        show_all["v"] = not show_all["v"]; refresh()
                    ui.button("Show all files" if not show_all["v"] else "Reports only",
                        icon="visibility", on_click=_toggle).props("flat no-caps size=sm color=grey")
                refresh()

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
