"""
JRI Pipeline V2 — Web UI (NiceGUI)

Run: python app.py
Opens at http://localhost:8080
"""
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from nicegui import ui, app

import config as cfg
from config import UI_PARAMS, apply_overrides

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ─── State ──────────────────────────────────────────
pipeline_state = {
    "running": False,
    "current_step": "",
    "current_phase": "",
    "progress": 0.0,
    "log_lines": [],
    "last_run": None,
}


# ─── Progress logger ───────────────────────────────
class UILogHandler(logging.Handler):
    """Captures log lines for the UI progress panel."""
    def __init__(self, state: dict, log_element=None):
        super().__init__()
        self.state = state
        self.log_element = log_element

    def emit(self, record):
        msg = self.format(record)
        self.state["log_lines"].append(msg)
        # Keep last 200 lines
        if len(self.state["log_lines"]) > 200:
            self.state["log_lines"] = self.state["log_lines"][-200:]


# ─── Pipeline runner ───────────────────────────────
async def run_pipeline_step(step: str, overrides: dict):
    """Run a pipeline step in background thread."""
    if pipeline_state["running"]:
        ui.notify("Pipeline is already running!", type="warning")
        return

    pipeline_state["running"] = True
    pipeline_state["current_step"] = step
    pipeline_state["log_lines"] = []
    pipeline_state["progress"] = 0.0

    # Apply parameter overrides
    apply_overrides(overrides)

    def _run():
        try:
            if step == "a1_cluster_generate":
                from steps.step_a1 import phase2_cluster, phase3_generate
                themes = phase2_cluster()
                phase3_generate(themes)
            elif step == "a1_rank":
                from steps.step_a1 import phase4_rank
                phase4_rank()
            elif step == "b_select":
                from steps.step_b import select_top_signals
                select_top_signals()
            elif step == "b_dedup":
                from steps.step_b import diversity_dedup
                diversity_dedup()
            elif step == "c_cluster":
                from steps.step_c import phase1_cluster, phase1_random
                if cfg.C_MODE == "random":
                    phase1_random()
                else:
                    phase1_cluster()
            elif step == "c_generate":
                from steps.step_c import phase2_generate
                phase2_generate()
            elif step == "c_rank":
                from steps.step_c import phase3_rank
                phase3_rank()
            elif step == "d_pair":
                from steps.step_d import phase1_select_pairs, phase1_random_pairs
                if cfg.D_MODE == "random":
                    phase1_random_pairs()
                else:
                    phase1_select_pairs()
            elif step == "d_generate":
                from steps.step_d import phase2_generate
                phase2_generate()
            elif step == "d_rank":
                from steps.step_d import phase3_rank
                phase3_rank()
            elif step == "rerank_a":
                from rerank import rerank_a
                rerank_a()
            elif step == "rerank_c":
                from rerank import rerank_c
                rerank_c()
            elif step == "rerank_d":
                from rerank import rerank_d
                rerank_d()
            pipeline_state["progress"] = 1.0
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            pipeline_state["log_lines"].append(f"ERROR: {e}")
        finally:
            pipeline_state["running"] = False
            pipeline_state["last_run"] = datetime.now().isoformat()

    await asyncio.get_event_loop().run_in_executor(None, _run)


# ─── UI ─────────────────────────────────────────────
@ui.page("/")
def main_page():
    ui.dark_mode(True)

    # Collect current override values
    param_values = {}

    with ui.header().classes("bg-blue-900 text-white items-center justify-between"):
        ui.label("JRI Pipeline V2").classes("text-xl font-bold")
        ui.label("Scenario Analysis Tool").classes("text-sm opacity-70")

    with ui.splitter(value=30).classes("w-full h-full") as splitter:
        # ─── Left: Parameters ───────────────────────
        with splitter.before:
            with ui.scroll_area().classes("h-full p-4"):
                ui.label("Parameters").classes("text-lg font-bold mb-2")

                # Group by section
                sections = {}
                for key, spec in UI_PARAMS.items():
                    sec = spec["section"]
                    if sec not in sections:
                        sections[sec] = []
                    sections[sec].append((key, spec))

                for section_name, params in sections.items():
                    with ui.expansion(section_name, icon="settings").classes("w-full"):
                        for key, spec in params:
                            default = spec["default"]
                            param_values[key] = default

                            if spec["type"] == "number":
                                slider = ui.number(
                                    label=spec["label"],
                                    value=default,
                                    min=spec.get("min", 0),
                                    max=spec.get("max", 100),
                                ).classes("w-full")
                                slider.on_value_change(
                                    lambda e, k=key: param_values.update({k: e.value})
                                )
                            elif spec["type"] == "bool":
                                switch = ui.switch(spec["label"], value=default)
                                switch.on_value_change(
                                    lambda e, k=key: param_values.update({k: e.value})
                                )
                            elif spec["type"] == "select":
                                select = ui.select(
                                    spec["options"],
                                    label=spec["label"],
                                    value=default,
                                ).classes("w-full")
                                select.on_value_change(
                                    lambda e, k=key: param_values.update({k: e.value})
                                )
                            elif spec["type"] == "text":
                                inp = ui.input(
                                    label=spec["label"],
                                    value=str(default),
                                ).classes("w-full")
                                inp.on_value_change(
                                    lambda e, k=key: param_values.update({k: e.value})
                                )

        # ─── Right: Actions & Results ───────────────
        with splitter.after:
            with ui.scroll_area().classes("h-full p-4"):
                ui.label("Pipeline Control").classes("text-lg font-bold mb-2")

                # Step buttons organized by stage
                with ui.card().classes("w-full mb-4"):
                    ui.label("A1 — Expected Scenarios").classes("font-bold")
                    ui.label("Summarization is locked (expensive). Clustering and below are available.").classes("text-xs opacity-60 mb-2")
                    with ui.row():
                        ui.button("Cluster + Generate", icon="hub",
                                  on_click=lambda: run_pipeline_step("a1_cluster_generate", param_values))
                        ui.button("Re-rank", icon="sort",
                                  on_click=lambda: run_pipeline_step("rerank_a", param_values))

                with ui.card().classes("w-full mb-4"):
                    ui.label("B — Weak Signal Selection").classes("font-bold")
                    ui.label("Scoring is locked (expensive). Selection and dedup are available.").classes("text-xs opacity-60 mb-2")
                    with ui.row():
                        ui.button("Select Top N", icon="filter_alt",
                                  on_click=lambda: run_pipeline_step("b_select", param_values))
                        ui.button("Diversity Dedup", icon="content_cut",
                                  on_click=lambda: run_pipeline_step("b_dedup", param_values))

                with ui.card().classes("w-full mb-4"):
                    ui.label("C — Unexpected Scenarios").classes("font-bold")
                    with ui.row():
                        ui.button("Cluster / Random Group", icon="hub",
                                  on_click=lambda: run_pipeline_step("c_cluster", param_values))
                        ui.button("Generate", icon="auto_awesome",
                                  on_click=lambda: run_pipeline_step("c_generate", param_values))
                        ui.button("Rank", icon="sort",
                                  on_click=lambda: run_pipeline_step("c_rank", param_values))

                with ui.card().classes("w-full mb-4"):
                    ui.label("D — Opportunity Scenarios").classes("font-bold")
                    with ui.row():
                        ui.button("Pair Selection", icon="shuffle",
                                  on_click=lambda: run_pipeline_step("d_pair", param_values))
                        ui.button("Generate", icon="auto_awesome",
                                  on_click=lambda: run_pipeline_step("d_generate", param_values))
                        ui.button("Rank", icon="sort",
                                  on_click=lambda: run_pipeline_step("d_rank", param_values))

                # ─── Progress & Logs ────────────────
                ui.separator()
                ui.label("Progress").classes("text-lg font-bold mt-4 mb-2")

                status_label = ui.label("Idle")
                progress_bar = ui.linear_progress(value=0).classes("w-full")
                log_area = ui.log(max_lines=100).classes("w-full h-64 mt-2")

                # ─── Results ────────────────────────
                ui.separator()
                ui.label("Results").classes("text-lg font-bold mt-4 mb-2")

                results_container = ui.column().classes("w-full")

                def refresh_results():
                    results_container.clear()
                    output_dir = cfg.OUTPUT_DIR
                    if not output_dir.exists():
                        with results_container:
                            ui.label("No output files yet.")
                        return
                    with results_container:
                        for f in sorted(output_dir.iterdir()):
                            if f.suffix in (".json", ".xlsx"):
                                size_kb = f.stat().st_size / 1024
                                with ui.row().classes("items-center gap-2"):
                                    ui.icon("description").classes("text-blue-400")
                                    ui.label(f"{f.name} ({size_kb:.0f} KB)").classes("text-sm")
                                    ui.button("Download", icon="download",
                                              on_click=lambda p=f: ui.download(str(p))).props("flat size=sm")

                ui.button("Refresh Results", icon="refresh", on_click=refresh_results).classes("mt-2")

                # ─── Timer: update progress display ──
                def update_display():
                    if pipeline_state["running"]:
                        status_label.text = f"Running: {pipeline_state['current_step']}"
                        progress_bar.value = pipeline_state["progress"]
                    else:
                        last = pipeline_state.get("last_run")
                        status_label.text = f"Idle (last run: {last})" if last else "Idle"
                        progress_bar.value = pipeline_state["progress"]

                    # Push new log lines
                    for line in pipeline_state["log_lines"]:
                        log_area.push(line)
                    pipeline_state["log_lines"] = []

                ui.timer(1.0, update_display)

    # Install log handler
    handler = UILogHandler(pipeline_state)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(handler)


# ─── Run ────────────────────────────────────────────
if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="JRI Pipeline V2", port=8080, reload=False)
