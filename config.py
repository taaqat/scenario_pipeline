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

load_dotenv(Path(__file__).parent / ".env")

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

B_MODEL_SCORE     = "gpt-5.2"    # B-score: 301 concurrent batches
B_MODEL_DIVERSITY = "gpt-5.2"    # B-diversity: single large call
RANK_MODEL        = "gpt-5.2"    # rank / select / score (A1-rank, C-rank, D-select, D-rank)
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
A1_MIN_DIM_SCORES = {"score_structural_depth": 5, "score_irreversibility": 5, "score_industry_relevance": 0, "score_topic_relevance": 0, "score_feasibility": 5}
A1_TOPIC_RELEVANCE_CAP = False   # If True: topic_relevance ≤ 3 → total_score capped at 15

# ─── Step B: Weak Signal Selection ───────────────────
B_INPUT_FILE = None        # Set by topic config
B_BATCH_SIZE = 25          # 每批評分幾筆（25: 平衡覆蓋率與呼叫次數）
B_TOP_N = None             # Set by topic config
B_DIVERSITY_BATCH = 600    # 每批去重幾筆（避免單次 call 輸出截斷）
B_MIN_DIM_SCORES = {"outside_area": 5, "novelty": 5, "social_impact": 5, "topic_relevance": 0}
B_TOPIC_RELEVANCE_CAP = False    # If True: topic_relevance ≤ 3 → total_score capped at 15

# ─── Step C: Unexpected Scenarios ────────────────────
C_GENERATE_N = None        # Set by topic config
C_MODE = "cluster"                         # "cluster" (k-means) or "random" (random grouping)
C_DIVERSITY_MAX_PCT = 40                   # Max % of final scenarios from a single theme
C_MIN_DIM_SCORES = {
    "score_unexpectedness": 5,
    "score_social_impact": 5,
    "score_uncertainty": 5,
}

# ─── Step D: Opportunity Scenarios ───────────────────
D_MODE = "hybrid"                          # "hybrid" (smart pair selection) or "random" (random A×C pairing)
D_GENERATE_N = None        # Set by topic config
D_MIN_DIM_SCORES = {"collision_score": 0, "unexpected_score": 5, "impact_score": 5, "plausibility_score": 5, "topic_relevance_score": 0}
D_PLAUSIBILITY_PASSFAIL = True   # If True: plausibility is pass/fail (≥ threshold), not counted in total
D_TOPIC_RELEVANCE_CAP = False    # If True: topic_relevance_score ≤ 3 → total_score capped at 20
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

    # Apply topic-specific settings
    cfg_module.TOPIC = tc.TOPIC
    cfg_module.TIMEFRAME = tc.TIMEFRAME
    cfg_module.CLIENT_PROFILE = tc.CLIENT_PROFILE
    cfg_module.A1_INPUT_FILE = INPUT_DIR / tc.A1_INPUT_FILE
    cfg_module.B_INPUT_FILE = INPUT_DIR / tc.B_INPUT_FILE

    # Generation counts (respect SMOKE_TEST)
    cfg_module.A1_GENERATE_N = 3 if SMOKE_TEST else tc.A1_GENERATE_N
    cfg_module.B_TOP_N = 20 if SMOKE_TEST else tc.B_TOP_N
    cfg_module.C_GENERATE_N = 5 if SMOKE_TEST else tc.C_GENERATE_N
    cfg_module.D_GENERATE_N = 5 if SMOKE_TEST else tc.D_GENERATE_N

    # Build writing style from topic examples
    cfg_module.WRITING_STYLE = _build_writing_style(
        tc.WRITING_STYLE_GOOD_EXAMPLE,
        tc.WRITING_STYLE_BAD_EXAMPLE,
        tc.JARGON_EXAMPLE_BEFORE,
        tc.JARGON_EXAMPLE_AFTER,
    )

    print(f"[config] Loaded topic: {tc.TOPIC}")
    print(f"[config] Client: {tc.CLIENT_PROFILE['name']}")
    print(f"[config] A1 input: {cfg_module.A1_INPUT_FILE.name}")
    print(f"[config] B input: {cfg_module.B_INPUT_FILE.name}")


# Auto-load default topic config on import
load_topic_config()


# ─── UI-adjustable parameter definitions ────────────
# Maps param name → {section, label, type, min, max, default, options}
# Used by the Web UI to render controls and by apply_overrides to validate.

UI_PARAMS = {
    # ── Global ──
    "TOPIC":        {"section": "Global", "label": "Research Topic", "hint": "The main theme AI will focus on. Changing this affects scoring in all steps — re-run needed.", "type": "text", "default": TOPIC, "priority": "main"},
    "TIMEFRAME":    {"section": "Global", "label": "Time Horizon", "hint": "How far into the future to look. Changing this affects scenario generation — re-run needed.", "type": "text", "default": TIMEFRAME, "priority": "main"},
    "INDUSTRIES":   {"section": "Global", "label": "Target Industries", "hint": "Comma-separated. AI will tailor scenarios to these industries. Changing this affects all steps — re-run needed.", "type": "text", "default": ", ".join(CLIENT_PROFILE["industries"]), "priority": "main"},
    "TRANSLATE_ENABLED": {"section": "Global", "label": "Translate to Chinese", "hint": "Translate all results from Japanese to Chinese. Adds ~10-20 min per step. OFF = Japanese only.", "type": "bool", "default": TRANSLATE_ENABLED, "priority": "main"},

    # ── A1 ──
    "A1_GENERATE_N":                {"section": "A1 Expected", "label": "Number of scenarios to generate", "hint": "More = broader coverage but slower. Recommended: 20.", "type": "number", "min": 5, "max": 100, "default": 20, "priority": "main"},
    "A1_SCORE_STRUCTURAL_DEPTH":    {"section": "A1 Expected", "label": "Min. Structural Depth", "hint": "How deeply must the scenario change industry structure? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "A1_SCORE_IRREVERSIBILITY":     {"section": "A1 Expected", "label": "Min. Irreversibility", "hint": "How hard to reverse the change? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "A1_SCORE_INDUSTRY_RELEVANCE":  {"section": "A1 Expected", "label": "Min. Industry Relevance", "hint": "How relevant to your industries? (0 = allow all)", "type": "number", "min": 0, "max": 10, "default": 0, "priority": "advanced"},
    "A1_SCORE_TOPIC_RELEVANCE":     {"section": "A1 Expected", "label": "Min. Topic Relevance", "hint": "How relevant to the research topic? (0 = allow all)", "type": "number", "min": 0, "max": 10, "default": 0, "priority": "advanced"},
    "A1_SCORE_FEASIBILITY":         {"section": "A1 Expected", "label": "Min. Feasibility", "hint": "Could this realistically happen in 10-15 years? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "A1_TOPIC_RELEVANCE_CAP":       {"section": "A1 Expected", "label": "Strict topic filter", "hint": "If ON, scenarios barely related to the topic are heavily penalized.", "type": "bool", "default": False, "priority": "advanced"},

    # ── B ──
    "B_TOP_N":                      {"section": "B Weak Signal", "label": "Number of signals to keep", "hint": "How many weak signals to pass to the next step. Recommended: 2000.", "type": "number", "min": 100, "max": 5000, "default": 2000, "priority": "main"},
    "B_SCORE_OUTSIDE_AREA":         {"section": "B Weak Signal", "label": "Min. Outside Area", "hint": "Must be outside your normal research scope? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "B_SCORE_NOVELTY":              {"section": "B Weak Signal", "label": "Min. Novelty", "hint": "Must be genuinely new information? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "B_SCORE_SOCIAL_IMPACT":        {"section": "B Weak Signal", "label": "Min. Social Impact", "hint": "Must have potential societal impact? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "B_SCORE_TOPIC_RELEVANCE":      {"section": "B Weak Signal", "label": "Min. Topic Relevance", "hint": "Must be related to the research topic? (0 = allow all)", "type": "number", "min": 0, "max": 10, "default": 0, "priority": "advanced"},
    "B_TOPIC_RELEVANCE_CAP":        {"section": "B Weak Signal", "label": "Strict topic filter", "hint": "If ON, signals barely related to the topic are heavily penalized.", "type": "bool", "default": False, "priority": "advanced"},

    # ── C ──
    "C_GENERATE_N":                 {"section": "C Unexpected", "label": "Number of scenarios to generate", "hint": "More = broader coverage but slower. Recommended: 100-150.", "type": "number", "min": 5, "max": 300, "default": 150, "priority": "main"},
    "C_MODE":                       {"section": "C Unexpected", "label": "Grouping mode", "hint": "Cluster = group similar signals. Random = mix signals from different areas for creative leaps.", "type": "select", "options": ["cluster", "random"], "default": "cluster", "priority": "main"},
    "C_DIVERSITY_MAX_PCT":          {"section": "C Unexpected", "label": "Max % per theme", "hint": "Prevent one topic from dominating. E.g., 40 = no single theme > 40% of results.", "type": "number", "min": 10, "max": 100, "default": 40, "priority": "advanced"},
    "C_SCORE_UNEXPECTEDNESS":       {"section": "C Unexpected", "label": "Min. Unexpectedness", "hint": "How surprising must the scenario be? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "C_SCORE_SOCIAL_IMPACT":        {"section": "C Unexpected", "label": "Min. Social Impact", "hint": "Must have potential societal impact? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "C_SCORE_UNCERTAINTY":          {"section": "C Unexpected", "label": "Min. Uncertainty", "hint": "Must be hard to predict? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},

    # ── D ──
    "D_GENERATE_N":                 {"section": "D Opportunity", "label": "Number of pairs to generate", "hint": "How many A x C combinations to explore. Recommended: 30-40.", "type": "number", "min": 5, "max": 100, "default": 40, "priority": "main"},
    "D_MODE":                       {"section": "D Opportunity", "label": "Pairing mode", "hint": "Hybrid = AI picks best pairs. Random = random combinations for creative exploration.", "type": "select", "options": ["hybrid", "random"], "default": "hybrid", "priority": "main"},
    "D_MATRIX_MODE":                {"section": "D Opportunity", "label": "Matrix classification", "hint": "Classify results into Unexpectedness x Impact quadrants (Breakthrough / Surprising / Incremental).", "type": "bool", "default": True, "priority": "main"},
    "D_SCORE_COLLISION":            {"section": "D Opportunity", "label": "Min. Collision Novelty", "hint": "How non-obvious must the A x C combination be? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 0, "priority": "advanced"},
    "D_SCORE_UNEXPECTED":           {"section": "D Opportunity", "label": "Min. Unexpectedness", "hint": "How surprising must the opportunity be? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "D_SCORE_IMPACT":               {"section": "D Opportunity", "label": "Min. Business Impact", "hint": "How big must the revenue/competitive impact be? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "D_SCORE_PLAUSIBILITY":         {"section": "D Opportunity", "label": "Min. Plausibility", "hint": "Must be realistically possible in 10-15 years? (0 = no filter)", "type": "number", "min": 0, "max": 10, "default": 5, "priority": "advanced"},
    "D_SCORE_TOPIC_RELEVANCE":      {"section": "D Opportunity", "label": "Min. Topic Relevance", "hint": "Must be related to the research topic? (0 = allow all)", "type": "number", "min": 0, "max": 10, "default": 0, "priority": "advanced"},
    "D_TOPIC_RELEVANCE_CAP":        {"section": "D Opportunity", "label": "Strict topic filter", "hint": "If ON, opportunities barely related to the topic are heavily penalized.", "type": "bool", "default": False, "priority": "advanced"},
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
        elif key.startswith("A1_SCORE_"):
            dim = "score_" + key[len("A1_SCORE_"):].lower()
            cfg_module.A1_MIN_DIM_SCORES[dim] = int(val)
        elif key == "A1_TOPIC_RELEVANCE_CAP":
            cfg_module.A1_TOPIC_RELEVANCE_CAP = bool(val)

        # B
        elif key == "B_TOP_N":
            cfg_module.B_TOP_N = int(val)
        elif key.startswith("B_SCORE_"):
            dim = key[len("B_SCORE_"):].lower()
            cfg_module.B_MIN_DIM_SCORES[dim] = int(val)
        elif key == "B_TOPIC_RELEVANCE_CAP":
            cfg_module.B_TOPIC_RELEVANCE_CAP = bool(val)

        # C
        elif key == "C_GENERATE_N":
            cfg_module.C_GENERATE_N = int(val)
        elif key == "C_MODE":
            cfg_module.C_MODE = val
        elif key == "C_DIVERSITY_MAX_PCT":
            cfg_module.C_DIVERSITY_MAX_PCT = int(val)
        elif key.startswith("C_SCORE_"):
            dim = "score_" + key[len("C_SCORE_"):].lower()
            cfg_module.C_MIN_DIM_SCORES[dim] = int(val)

        # D
        elif key == "D_GENERATE_N":
            cfg_module.D_GENERATE_N = int(val)
        elif key == "D_MODE":
            cfg_module.D_MODE = val
        elif key.startswith("D_SCORE_"):
            dim = key[len("D_SCORE_"):].lower() + "_score"
            # Handle naming: collision_score, unexpected_score, etc.
            dim_map = {
                "collision_score": "collision_score",
                "unexpected_score": "unexpected_score",
                "impact_score": "impact_score",
                "plausibility_score": "plausibility_score",
                "topic_relevance_score": "topic_relevance_score",
            }
            cfg_module.D_MIN_DIM_SCORES[dim_map.get(dim, dim)] = int(val)
        elif key == "D_TOPIC_RELEVANCE_CAP":
            cfg_module.D_TOPIC_RELEVANCE_CAP = bool(val)
        elif key == "D_MATRIX_MODE":
            cfg_module.D_MATRIX_MODE = bool(val)
