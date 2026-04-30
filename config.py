"""
AI Scenario Pipeline — Configuration

All parameters below are defaults. Use `apply_overrides(dict)` to override
from the Web UI without editing this file.

Topic-specific settings (TOPIC, CLIENT_PROFILE, input files, generation counts)
are loaded from configs/*.py via `load_topic_config()`.
Default: configs/jri_aging.py
"""
import os
import importlib.util
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

# ─── Paths ───────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
PROMPTS_DIR = BASE_DIR / "prompts"

# ─── API ─────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    import warnings
    warnings.warn("ANTHROPIC_API_KEY not set — Claude API calls will fail", stacklevel=2)

MODEL_HEAVY  = "claude-opus-4-6"          # cluster, generate, synthesize
MODEL_STRONG = "claude-sonnet-4-6"        # fallback default (MODEL_PRIMARY alias)
MODEL_PRIMARY = MODEL_STRONG              # alias used by llm_client
MODEL_LIGHT = "claude-haiku-4-5-20251001" # summarize (A1 Phase1)
MAX_TOKENS = 8192

# OpenAI (Step B + translation)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    import warnings
    warnings.warn("OPENAI_API_KEY not set — OpenAI API calls will fail", stacklevel=2)

B_MODEL_SCORE     = "gpt-5.4"    # B-score: 301 concurrent batches
B_MODEL_DIVERSITY = "gpt-5.4"    # B-diversity: single large call
RANK_MODEL        = "gpt-5.4"    # rank / select / score (A1-rank, C-rank, D-select, D-rank)
TRANSLATE_MODEL   = "gpt-5"   # ja→zh translation (all steps) — 翻譯不需最強模型
TRANSLATE_ENABLED = False      # Set True to translate ja→zh (adds ~10-20 min per step)

# Rate limiting
RPM_LIMIT = 50          # requests per minute (self-imposed ceiling)
MAX_CONCURRENT = 10      # parallel API calls for Phase 1 summarization
RETRY_MAX = 3
RETRY_DELAY = 5         # seconds between retries

# ─── Smoke Test (set False for full production run) ──
SMOKE_TEST = False
SMOKE_ROWS = 50            # max input rows for A1 & B when smoke testing

# ─── Step A-1: Expected Scenarios ────────────────────
A1_INPUT_FILE = None       # Set by topic config
A1_PHASE1_BATCH = 10       # 每批摘要幾篇文章
A1_PHASE2_BATCH = 50       # 每批歸納幾篇摘要 → 主題
A1_GENERATE_N = None       # Set by topic config
A1_WEIGHTS = {"structural_depth": 1, "irreversibility": 1, "industry_related": 1, "topic_relevance": 1, "feasibility": 1}  # 0-10 per dim. industry_related = customer-original criterion; topic_relevance = our addition (kept separate per user instruction)

# ─── Step B: Weak Signal Selection ───────────────────
B_INPUT_FILE = None        # Set by topic config
B_BATCH_SIZE = 25          # 每批評分幾筆（25: 平衡覆蓋率與呼叫次數）
B_TOP_N = None             # Set by topic config
B_DIVERSITY_BATCH = 600    # 每批去重幾筆（避免單次 call 輸出截斷）
B_WEIGHTS = {"outside_area": 1, "novelty": 1, "social_impact": 1}  # 0-10 per dim; applied when re-ranking cached Phase 1 scores

# ─── Step C: Unexpected Scenarios ────────────────────
C_GENERATE_N = None        # Set by topic config
# ─── Over-generation + diversity-aware top-K (system-managed, hidden from UI) ──
# For each step:
#   - *_GENERATE_N (in UI_PARAMS below) is what the CLIENT asks for: "I want N final scenarios"
#   - we generate min(client_N * OVERGEN_FACTOR, GENERATE_CAP) candidates internally
#   - rank them all, then select_diverse_topk -> top client_N by score & topic diversity
# OVERGEN_FACTOR is bigger for A1 because A1 needs a larger pool to be diverse
# (BERTopic produces fewer real clusters when min_cluster_size is high).
# C/D already use forced collision so 2x is enough.
A1_OVERGEN_FACTOR = 3
A1_GENERATE_CAP   = 100
A1_BERTOPIC_MIN_CLUSTER_SIZE = 30  # HDBSCAN min cluster size; lower = more granular, more outliers
A1_BERTOPIC_DROP_OUTLIERS = True   # drop HDBSCAN noise bucket (-1) — incoherent for LLM labeling
C_OVERGEN_FACTOR  = 2
C_GENERATE_CAP    = 200
C_BERTOPIC_MIN_CLUSTER_SIZE = 15  # smaller than A1 because signals are shorter and pool size is smaller
C_BERTOPIC_DROP_OUTLIERS = True
D_OVERGEN_FACTOR  = 2
D_GENERATE_CAP    = 60
C_MODE = "cluster_pair"                    # "cluster" | "cluster_pair" | "signal_pair"
C_WEIGHTS = {"unexpectedness": 1, "social_impact": 1, "uncertainty": 1}  # 0-5 per dim

# ─── Step D: Opportunity Scenarios ───────────────────
D_MODE = "random"                          # "random" (random A×C pairing) — hybrid retired
D_GENERATE_N = None        # Set by topic config
D_WEIGHTS = {"unexpected_score": 1, "impact_score": 1, "plausibility_score": 1}  # all 3 dims weighted; matrix axes still = Unexpectedness × Impact
D_MATRIX_MODE = True             # If True: classify scenarios into Unexpectedness × Impact matrix


# ─── Project Context (set by topic config) ───────────
TOPIC = None
TIMEFRAME = None
WRITING_STYLE = None
CLIENT_PROFILE = None

# ─── Default topic config ────────────────────────────
_DEFAULT_TOPIC_CONFIG = "configs/jri_aging.py"


def _build_writing_style(good_example, bad_example, jargon_before, jargon_after):
    """Build WRITING_STYLE string from topic-specific examples."""
    return f"""\
# WRITING STYLE — Top Priority
These scenarios are workshop materials. Participants will scan them in seconds, so clarity beats completeness.
- Write like a sharp management consultant briefing a CEO: one idea per sentence, no filler, no jargon chains.
- Titles must be vivid and specific — the reader should picture a concrete scene, not an abstract concept. Good: {good_example} Bad: {bad_example}
- Lead every paragraph with the punchline. Support with 1-2 concrete details, then stop.
- Favor surprising, counterintuitive angles over comprehensive coverage. The goal is to provoke "I never thought of that" — not to summarize everything we know.

# JAPANESE WRITING QUALITY — 日本語の書き方ルール
- 一文は60字以内を目安にする。読点（、）が3つ以上ある文は分割する。
- 名詞の連続（「高齢者支援型デジタル統合ケアプラットフォーム」のような漢字チェーン）は禁止。最長4漢字で区切り、助詞を入れて読みやすくする。
- 行政・学術用語をそのまま使わない。{jargon_before}→{jargon_after}のように、仕組みを具体的に書く。
- 主語を省略しすぎない。誰が・何がを明示する。
- 体言止め（名詞で文を終える）は見出し以外では使わない。
- 数字は必ず半角アラビア数字を使う（×：二千五十七 → ○：2,057）。"""


def load_topic_config(config_path: str = None):
    """
    Load a topic config file and apply it to this module's globals.
    Called by run_pipeline.py at startup.

    Usage:
        import config as cfg
        cfg.load_topic_config("configs/energy.py")
    """
    import config as cfg_module

    if config_path is None:
        config_path = _DEFAULT_TOPIC_CONFIG

    path = Path(config_path)
    if not path.is_absolute():
        path = BASE_DIR / path

    if not path.exists():
        raise FileNotFoundError(f"Topic config not found: {path}")

    # Load the topic config as a module
    spec = importlib.util.spec_from_file_location("topic_config", path)
    tc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tc)

    # Per-topic subdirectories (input, output, intermediate) — must be set before input file paths
    output_subdir = getattr(tc, "OUTPUT_SUBDIR", None)
    if output_subdir:
        cfg_module.INPUT_DIR = DATA_DIR / "input" / output_subdir
        cfg_module.INPUT_DIR.mkdir(parents=True, exist_ok=True)
        cfg_module.OUTPUT_DIR = DATA_DIR / "output" / output_subdir
        cfg_module.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        cfg_module.INTERMEDIATE_DIR = DATA_DIR / "intermediate" / output_subdir
        cfg_module.INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)

    # Apply topic-specific settings
    cfg_module.TOPIC = tc.TOPIC
    cfg_module.TIMEFRAME = tc.TIMEFRAME
    cfg_module.OUTPUT_LANGUAGE = getattr(tc, "OUTPUT_LANGUAGE", "日本語")
    cfg_module.CLIENT_PROFILE = tc.CLIENT_PROFILE
    cfg_module.A1_INPUT_FILE = cfg_module.INPUT_DIR / tc.A1_INPUT_FILE
    cfg_module.B_INPUT_FILE = cfg_module.INPUT_DIR / tc.B_INPUT_FILE

    # Generation counts (respect SMOKE_TEST)
    cfg_module.A1_GENERATE_N = 3 if SMOKE_TEST else tc.A1_GENERATE_N
    cfg_module.B_TOP_N = 20 if SMOKE_TEST else tc.B_TOP_N
    cfg_module.C_GENERATE_N = 5 if SMOKE_TEST else tc.C_GENERATE_N
    cfg_module.D_GENERATE_N = 5 if SMOKE_TEST else tc.D_GENERATE_N

    # Writing style: use topic's override if provided, otherwise build from examples
    if hasattr(tc, "WRITING_STYLE") and tc.WRITING_STYLE:
        cfg_module.WRITING_STYLE = tc.WRITING_STYLE
    else:
        cfg_module.WRITING_STYLE = _build_writing_style(
            tc.WRITING_STYLE_GOOD_EXAMPLE,
            tc.WRITING_STYLE_BAD_EXAMPLE,
            tc.JARGON_EXAMPLE_BEFORE,
            tc.JARGON_EXAMPLE_AFTER,
        )

    print(f"[config] Loaded topic: {tc.TOPIC}")
    print(f"[config] Client: {tc.CLIENT_PROFILE['name']}")
    print(f"[config] Output: {cfg_module.OUTPUT_DIR}")
    print(f"[config] A1 input: {cfg_module.A1_INPUT_FILE.name}")
    print(f"[config] B input: {cfg_module.B_INPUT_FILE.name}")


# Auto-load default topic config on import
load_topic_config()


# ─── UI-adjustable parameter definitions ────────────
# Maps param name → {section, label, type, min, max, default, options}
# Used by the Web UI to render controls and by apply_overrides to validate.

UI_PARAMS = {
    # ── Global ──
    "TOPIC":        {"section": "Global", "label": "Research Topic", "hint": "The core subject of the analysis. ⚠ If you change this, re-run all four steps (① → ② → ③ → ④).", "type": "text", "default": TOPIC, "priority": "main"},
    "TIMEFRAME":    {"section": "Global", "label": "Time Horizon", "hint": "The future window the scenarios should describe (e.g. \"Next 10-15 years\"). ⚠ If you change this, re-run all four steps.", "type": "text", "default": TIMEFRAME, "priority": "main"},
    "INDUSTRIES":   {"section": "Global", "label": "Target Industries", "hint": "Industries the client cares about, comma-separated. ⚠ If you change this, re-run all four steps.", "type": "text", "default": ", ".join(CLIENT_PROFILE["industries"]), "priority": "main"},

    # ── A1 ──
    "A1_GENERATE_N":                {"section": "A1 Expected", "label": "Number of scenarios to deliver", "label_suffix": " (max 30 — test-phase limit)", "hint": "Final number of expected scenarios shown to the client. The system over-generates candidates internally and then picks the most representative ones for diversity.", "type": "number", "min": 5, "max": 30, "default": 10, "priority": "main"},
    "A1_WEIGHT_STRUCTURAL_DEPTH":   {"section": "A1 Expected", "label": "Weight: Structural Depth", "hint": "Changes basic operating models or value chain.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
    "A1_WEIGHT_IRREVERSIBILITY":    {"section": "A1 Expected", "label": "Weight: Irreversibility", "hint": "Too costly or practically impossible to return to previous models or operational systems once the change is implemented.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
    "A1_WEIGHT_INDUSTRY_RELATED":   {"section": "A1 Expected", "label": "Weight: Industry-related", "hint": "Directly affects core industry processes.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
    "A1_WEIGHT_TOPIC_RELEVANCE":    {"section": "A1 Expected", "label": "Weight: Topic relevance", "hint": "How directly the scenario relates to the project topic.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
    "A1_WEIGHT_FEASIBILITY":        {"section": "A1 Expected", "label": "Weight: Feasibility", "hint": "Realistically achievable in 10-15 years.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},

    # ── B ──
    "B_TOP_N":                      {"section": "B Weak Signal", "label": "Number of signals to keep", "label_suffix": " (max 2000 — test-phase limit)", "hint": "How many weak signals to pass to Unexpected Scenarios. Adjusting the weights below changes which signals get selected.", "type": "number", "min": 100, "max": 2000, "default": 2000, "priority": "main"},
    "B_WEIGHT_OUTSIDE_AREA":        {"section": "B Weak Signal", "label": "Weight: Outside client's area", "hint": "Information outside the perspective of the client company's employees (areas they normally investigate).", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
    "B_WEIGHT_NOVELTY":             {"section": "B Weak Signal", "label": "Weight: Novelty", "hint": "Information that is entirely new / unheard-of to the clients.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
    "B_WEIGHT_SOCIAL_IMPACT":       {"section": "B Weak Signal", "label": "Weight: Social Impact", "hint": "Could affect broad social dimensions if developed.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},

    # ── C ──
    "C_GENERATE_N":                 {"section": "C Unexpected", "label": "Number of scenarios to deliver", "label_suffix": " (max 100 — test-phase limit)", "hint": "Final number of unexpected scenarios shown to the client. The system over-generates candidates internally and then picks the most representative ones for diversity.", "type": "number", "min": 5, "max": 100, "default": 10, "priority": "main"},
    "C_MODE":                       {"section": "C Unexpected", "label": "How to combine signals", "hint": "One topic = pair signals on similar topics (safest). Two topics = pair signals from two different topic groups, e.g. one health + one energy (recommended). Random = pair any 2 signals regardless of topic (wildest).", "type": "select", "options": {"cluster": "One topic per scenario (safest)", "cluster_pair": "Two topics per scenario (recommended)", "signal_pair": "Random signals (wildest)"}, "default": "cluster_pair", "priority": "main"},
    "C_WEIGHT_UNEXPECTEDNESS":      {"section": "C Unexpected", "label": "Weight: Unexpectedness", "hint": "Outside normal forecasts or mainstream discussions, AND on a personal level, ideas that hardly come to mind in one's daily life and are hard to envision.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
    "C_WEIGHT_SOCIAL_IMPACT":       {"section": "C Unexpected", "label": "Weight: Social Impact", "hint": "Changes how most people live or how society functions.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
    "C_WEIGHT_UNCERTAINTY":         {"section": "C Unexpected", "label": "Weight: Uncertainty", "hint": "Hard to anticipate, evaluate, or verify the likelihood — even an expert cannot determine whether the event will occur.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},

    # ── D ──
    "D_GENERATE_N":                 {"section": "D Opportunity", "label": "Number of opportunities to deliver", "label_suffix": " (max 30 — test-phase limit)", "hint": "Final number of opportunity scenarios shown to the client. The system over-generates candidates internally and then picks the most representative ones for diversity.", "type": "number", "min": 5, "max": 30, "default": 10, "priority": "main"},
    "D_MATRIX_MODE":                {"section": "D Opportunity", "label": "Matrix classification", "hint": "Plot opportunities on an Unexpectedness × Business Impact chart and tag each one as Breakthrough, Surprising, Incremental, or Low Priority. Adds the matrix view to the Results tab.", "type": "bool", "default": True, "priority": "main"},
    "D_WEIGHT_UNEXPECTED":          {"section": "D Opportunity", "label": "Weight: Unexpectedness", "hint": "Not included in research outputs that determine current business strategies.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
    "D_WEIGHT_IMPACT":              {"section": "D Opportunity", "label": "Weight: Business Impact", "hint": "Could significantly change revenue structure or competitive advantage.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
    "D_WEIGHT_PLAUSIBILITY":        {"section": "D Opportunity", "label": "Weight: Plausibility", "hint": "How realistically the opportunity could happen in 10-15 years.", "type": "number", "min": 0, "max": 10, "default": 1, "priority": "advanced"},
}


def apply_overrides(overrides: dict):
    """
    Apply UI parameter overrides to this module's globals.
    Call this BEFORE running any pipeline step.
    """
    import config as cfg_module

    for key, val in overrides.items():
        # Global context
        if key == "TOPIC":
            cfg_module.TOPIC = val
        elif key == "TIMEFRAME":
            cfg_module.TIMEFRAME = val
        elif key == "INDUSTRIES":
            industries = [s.strip() for s in val.split(",") if s.strip()]
            cfg_module.CLIENT_PROFILE["industries"] = industries
        elif key == "TRANSLATE_ENABLED":
            cfg_module.TRANSLATE_ENABLED = bool(val)

        # A1
        elif key == "A1_GENERATE_N":
            cfg_module.A1_GENERATE_N = int(val)
        elif key.startswith("A1_WEIGHT_"):
            dim = key[len("A1_WEIGHT_"):].lower()
            cfg_module.A1_WEIGHTS[dim] = float(val)

        # B
        elif key == "B_TOP_N":
            cfg_module.B_TOP_N = int(val)
        elif key.startswith("B_WEIGHT_"):
            dim = key[len("B_WEIGHT_"):].lower()
            cfg_module.B_WEIGHTS[dim] = float(val)

        # C
        elif key == "C_GENERATE_N":
            cfg_module.C_GENERATE_N = int(val)
        elif key == "C_MODE":
            cfg_module.C_MODE = val
        elif key.startswith("C_WEIGHT_"):
            dim = key[len("C_WEIGHT_"):].lower()
            cfg_module.C_WEIGHTS[dim] = float(val)

        # D
        elif key == "D_GENERATE_N":
            cfg_module.D_GENERATE_N = int(val)
        elif key == "D_MODE":
            cfg_module.D_MODE = val
        elif key.startswith("D_WEIGHT_"):
            dim = key[len("D_WEIGHT_"):].lower() + "_score"
            cfg_module.D_WEIGHTS[dim] = float(val)
        elif key == "D_MATRIX_MODE":
            cfg_module.D_MATRIX_MODE = bool(val)
