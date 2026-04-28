"""
AI Scenario Pipeline — Streamlit Web Interface
==============================================
Streamlit deployment version for running the scenario generation pipeline.

Usage:
    streamlit run streamlit_app.py
"""
import streamlit as st
import sys
import logging
import json
from pathlib import Path
from datetime import datetime
import traceback

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from steps import step_a1, step_b, step_c, step_d
from utils.llm_client import get_client
from utils.openai_client import get_openai_client
from utils.data_io import save_json, read_json

# ─── Page Configuration ─────────────────────────────────
st.set_page_config(
    page_title="AI Scenario Pipeline",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Custom CSS ─────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f2937;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #6b7280;
        margin-bottom: 2rem;
    }
    .step-card {
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #e5e7eb;
        margin: 0.5rem 0;
    }
    .success-box {
        padding: 1rem;
        background-color: #d1fae5;
        border-left: 4px solid #10b981;
        border-radius: 0.25rem;
        margin: 1rem 0;
    }
    .error-box {
        padding: 1rem;
        background-color: #fee2e2;
        border-left: 4px solid #ef4444;
        border-radius: 0.25rem;
        margin: 1rem 0;
    }
    .info-box {
        padding: 1rem;
        background-color: #dbeafe;
        border-left: 4px solid #3b82f6;
        border-radius: 0.25rem;
        margin: 1rem 0;
    }
    .metric-card {
        text-align: center;
        padding: 1rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)


# ─── Logging Setup ──────────────────────────────────────
def setup_logging():
    """Setup logging for the pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(cfg.BASE_DIR / "pipeline.log", encoding="utf-8"),
        ],
    )


# ─── Session State Initialization ──────────────────────
if "pipeline_running" not in st.session_state:
    st.session_state.pipeline_running = False
if "last_run_results" not in st.session_state:
    st.session_state.last_run_results = None
if "cost_report" not in st.session_state:
    st.session_state.cost_report = None
if "selected_config" not in st.session_state:
    st.session_state.selected_config = "jri_aging"


# ─── Helper Functions ───────────────────────────────────
def ensure_dirs():
    """Create data directories if they don't exist."""
    for d in [cfg.INPUT_DIR, cfg.OUTPUT_DIR, cfg.INTERMEDIATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_topic_config(config_name):
    """Load topic configuration from configs/ directory."""
    from config import load_topic_config
    config_path = cfg.BASE_DIR / "configs" / f"{config_name}.py"
    if config_path.exists():
        load_topic_config(str(config_path))
        return True
    return False


def save_cost_report():
    """Generate and save cost report."""
    client = get_client()
    client.tracker.print_summary()
    report = client.tracker.to_report()
    
    # Merge OpenAI usage
    openai_report = get_openai_client().cost_report()
    for step, data in openai_report.items():
        if step.startswith("_"):
            continue
        report["by_step"][step] = data
    
    # Recompute totals
    in_ = sum(v.get("input_tokens", 0) for v in report["by_step"].values())
    out_ = sum(v.get("output_tokens", 0) for v in report["by_step"].values())
    report["total"] = {
        "calls": sum(v.get("calls", 0) for v in report["by_step"].values()),
        "input_tokens": in_,
        "output_tokens": out_,
        "total_tokens": in_ + out_,
        "cost_usd": round(sum(v.get("cost_usd", 0) for v in report["by_step"].values()), 4),
    }
    
    save_json(report, cfg.OUTPUT_DIR / "cost_report.json")
    return report


def run_step_safe(step_name, step_func):
    """Run a single step with error handling."""
    logger = logging.getLogger("pipeline")
    try:
        logger.info(f"Starting Step {step_name}")
        result = step_func()
        if result is None:
            logger.warning(f"Step {step_name} returned None")
            return []
        logger.info(f"Step {step_name} completed: {len(result)} items")
        return result
    except Exception as e:
        logger.exception(f"Step {step_name} FAILED")
        st.error(f"❌ Step {step_name} failed: {str(e)}")
        st.code(traceback.format_exc())
        return []


def run_full_pipeline():
    """Run the complete pipeline A1 → B → C → D."""
    logger = logging.getLogger("pipeline")
    logger.info("Starting full pipeline")
    
    # Reset cost trackers
    get_client().tracker.reset()
    get_openai_client().reset_cost()
    
    results = {}
    step_definitions = [
        ("A-1", "expected", step_a1.run, "📊 Expected Scenarios"),
        ("B", "selected_signals", step_b.run, "📡 Weak Signals Selection"),
        ("C", "unexpected", step_c.run, "🔮 Unexpected Scenarios"),
        ("D", "opportunities", step_d.run, "💡 Opportunity Scenarios"),
    ]
    
    # Create progress containers
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, (label, key, func, description) in enumerate(step_definitions):
        status_text.markdown(f"**{description}**")
        
        with st.expander(f"Step {label}: {description}", expanded=True):
            start_time = datetime.now()
            result = run_step_safe(label, func)
            duration = (datetime.now() - start_time).total_seconds()
            
            results[key] = result
            
            if result:
                st.success(f"✅ Generated {len(result)} items in {duration:.1f}s")
            else:
                st.warning(f"⚠️ Step produced 0 results")
        
        progress_bar.progress((idx + 1) / len(step_definitions))
    
    status_text.markdown("**✨ Pipeline Complete!**")
    
    # Save cost report
    cost_report = save_cost_report()
    
    return results, cost_report


def run_single_step(step_choice):
    """Run a single pipeline step."""
    # Reset cost trackers
    get_client().tracker.reset()
    get_openai_client().reset_cost()
    
    step_map = {
        "Step A-1: Expected Scenarios": ("A-1", step_a1.run),
        "Step B: Weak Signals Selection": ("B", step_b.run),
        "Step C: Unexpected Scenarios": ("C", step_c.run),
        "Step D: Opportunity Scenarios": ("D", step_d.run),
    }
    
    label, func = step_map[step_choice]
    
    with st.spinner(f"Running Step {label}..."):
        start_time = datetime.now()
        result = run_step_safe(label, func)
        duration = (datetime.now() - start_time).total_seconds()
    
    cost_report = save_cost_report()
    
    return {label: result}, cost_report, duration


# ─── Main Interface ─────────────────────────────────────
def main():
    # Header
    st.markdown('<div class="main-header">🔮 AI Scenario Pipeline</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Generate future scenarios using AI-powered analysis</div>', unsafe_allow_html=True)
    
    # Sidebar Configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Topic Selection
        st.subheader("1️⃣ Select Topic")
        config_options = {
            "JRI Aging Society": "jri_aging",
            "Energy Sustainability": "energy"
        }
        selected_topic = st.selectbox(
            "Topic Configuration",
            options=list(config_options.keys()),
            key="topic_selector"
        )
        st.session_state.selected_config = config_options[selected_topic]
        
        # Load config
        if load_topic_config(st.session_state.selected_config):
            st.success(f"✓ Loaded: {cfg.TOPIC}")
        
        st.divider()
        
        # Step Selection
        st.subheader("2️⃣ Select Step(s)")
        run_mode = st.radio(
            "Run Mode",
            ["Full Pipeline (A→B→C→D)", "Single Step"],
            key="run_mode"
        )
        
        if run_mode == "Single Step":
            step_choice = st.selectbox(
                "Select Step",
                [
                    "Step A-1: Expected Scenarios",
                    "Step B: Weak Signals Selection",
                    "Step C: Unexpected Scenarios",
                    "Step D: Opportunity Scenarios"
                ]
            )
        
        st.divider()
        
        # Advanced Settings
        with st.expander("🔧 Advanced Settings"):
            st.markdown("**Generation Counts**")
            a1_count = st.number_input("A-1 Scenarios", value=10, min_value=1, max_value=50)
            b_count = st.number_input("B Top Signals", value=2000, min_value=100, max_value=5000, step=100)
            c_count = st.number_input("C Scenarios", value=10, min_value=1, max_value=50)
            d_count = st.number_input("D Opportunities", value=10, min_value=1, max_value=50)
            
            translate = st.checkbox("Enable Translation (ja→zh)", value=False)
            
            if st.button("Apply Settings"):
                from config import apply_overrides
                apply_overrides({
                    "A1_GENERATE_N": a1_count,
                    "B_TOP_N": b_count,
                    "C_GENERATE_N": c_count,
                    "D_GENERATE_N": d_count,
                    "TRANSLATE_ENABLED": translate
                })
                st.success("✓ Settings applied")
        
        st.divider()
        
        # API Status
        st.subheader("🔑 API Status")
        if cfg.ANTHROPIC_API_KEY:
            st.success("✓ Claude API")
        else:
            st.error("✗ Claude API")
        
        if cfg.OPENAI_API_KEY:
            st.success("✓ OpenAI API")
        else:
            st.error("✗ OpenAI API")
    
    # Main Content Area
    tab1, tab2, tab3 = st.tabs(["🚀 Run Pipeline", "📊 Results", "💰 Cost Report"])
    
    # Tab 1: Run Pipeline
    with tab1:
        st.header("Run Pipeline")
        
        # Info Box
        st.markdown("""
        <div class="info-box">
            <strong>ℹ️ About the Pipeline</strong><br>
            This pipeline generates future scenarios through 4 steps:<br>
            • <strong>Step A-1:</strong> Analyze trends and generate expected scenarios<br>
            • <strong>Step B:</strong> Select weak signals for unexpected scenario generation<br>
            • <strong>Step C:</strong> Generate unexpected scenarios from weak signals<br>
            • <strong>Step D:</strong> Create opportunity scenarios by combining expected and unexpected scenarios
        </div>
        """, unsafe_allow_html=True)
        
        # Run Button
        col1, col2, col3 = st.columns([2, 1, 2])
        with col2:
            if st.button("▶️ Run Pipeline", type="primary", use_container_width=True, disabled=st.session_state.pipeline_running):
                st.session_state.pipeline_running = True
                
                # Setup
                setup_logging()
                ensure_dirs()
                
                # Run pipeline
                try:
                    if run_mode == "Full Pipeline (A→B→C→D)":
                        results, cost_report = run_full_pipeline()
                        st.session_state.last_run_results = results
                        st.session_state.cost_report = cost_report
                        
                        # Summary
                        st.balloons()
                        st.markdown("""
                        <div class="success-box">
                            <strong>✨ Pipeline Complete!</strong><br>
                            All steps executed successfully. Check the Results and Cost Report tabs.
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        results, cost_report, duration = run_single_step(step_choice)
                        st.session_state.last_run_results = results
                        st.session_state.cost_report = cost_report
                        
                        st.success(f"✅ Step completed in {duration:.1f}s")
                
                except Exception as e:
                    st.error(f"❌ Pipeline failed: {str(e)}")
                    st.code(traceback.format_exc())
                
                finally:
                    st.session_state.pipeline_running = False
    
    # Tab 2: Results
    with tab2:
        st.header("Pipeline Results")
        
        if st.session_state.last_run_results is None:
            st.info("👈 Run the pipeline first to see results here")
        else:
            results = st.session_state.last_run_results
            
            # Summary Metrics
            col1, col2, col3, col4 = st.columns(4)
            metrics = [
                ("Expected", "expected", "📊"),
                ("Weak Signals", "selected_signals", "📡"),
                ("Unexpected", "unexpected", "🔮"),
                ("Opportunities", "opportunities", "💡")
            ]
            
            for col, (label, key, icon) in zip([col1, col2, col3, col4], metrics):
                with col:
                    count = len(results.get(key, []))
                    st.metric(f"{icon} {label}", count)
            
            st.divider()
            
            # Display Results by Step
            for label, key, icon in metrics:
                if key in results and results[key]:
                    with st.expander(f"{icon} {label} Scenarios ({len(results[key])} items)", expanded=False):
                        items = results[key][:5]  # Show first 5
                        for i, item in enumerate(items, 1):
                            st.markdown(f"**{i}.** {item.get('scenario_title_ja', item.get('scenario_title', 'Untitled'))}")
                            if 'scenario_description_ja' in item:
                                st.caption(item['scenario_description_ja'][:200] + "...")
                            st.divider()
                        
                        if len(results[key]) > 5:
                            st.info(f"... and {len(results[key]) - 5} more items")
            
            # Download Section
            st.divider()
            st.subheader("📥 Download Results")
            
            # Check for output files
            output_files = list(cfg.OUTPUT_DIR.glob("*.json"))
            if output_files:
                cols = st.columns(len(output_files))
                for col, file_path in zip(cols, output_files):
                    with col:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            st.download_button(
                                label=f"📄 {file_path.name}",
                                data=f.read(),
                                file_name=file_path.name,
                                mime="application/json"
                            )
    
    # Tab 3: Cost Report
    with tab3:
        st.header("Cost Report")
        
        if st.session_state.cost_report is None:
            st.info("👈 Run the pipeline first to see cost report here")
        else:
            report = st.session_state.cost_report
            
            # Total Cost
            total = report.get("total", {})
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("Total Cost", f"${total.get('cost_usd', 0):.4f}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col2:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("API Calls", f"{total.get('calls', 0):,}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col3:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("Input Tokens", f"{total.get('input_tokens', 0):,}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            with col4:
                st.markdown('<div class="metric-card">', unsafe_allow_html=True)
                st.metric("Output Tokens", f"{total.get('output_tokens', 0):,}")
                st.markdown('</div>', unsafe_allow_html=True)
            
            st.divider()
            
            # Cost by Step
            st.subheader("Cost Breakdown by Step")
            by_step = report.get("by_step", {})
            
            if by_step:
                import pandas as pd
                
                rows = []
                for step, data in by_step.items():
                    rows.append({
                        "Step": step,
                        "Calls": data.get("calls", 0),
                        "Input Tokens": f"{data.get('input_tokens', 0):,}",
                        "Output Tokens": f"{data.get('output_tokens', 0):,}",
                        "Cost (USD)": f"${data.get('cost_usd', 0):.4f}"
                    })
                
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Download cost report
            st.download_button(
                label="📊 Download Full Cost Report (JSON)",
                data=json.dumps(report, indent=2, ensure_ascii=False),
                file_name=f"cost_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )


if __name__ == "__main__":
    main()
