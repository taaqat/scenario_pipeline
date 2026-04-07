"""
JRI Living Lab+ AI Scenario Pipeline — Configuration

All parameters below are defaults. Use `apply_overrides(dict)` to override
from the Web UI without editing this file.
"""
import os
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

# Rate limiting
RPM_LIMIT = 50          # requests per minute (self-imposed ceiling)
MAX_CONCURRENT = 10      # parallel API calls for Phase 1 summarization
RETRY_MAX = 3
RETRY_DELAY = 5         # seconds between retries

# ─── Smoke Test (set False for full production run) ──
SMOKE_TEST = False
SMOKE_ROWS = 50            # max input rows for A1 & B when smoke testing

# ─── Step A-1: Expected Scenarios ────────────────────
A1_INPUT_FILE = INPUT_DIR / "日本 JRI aging 7240 rows.xlsx"
A1_PHASE1_BATCH = 10       # 每批摘要幾篇文章
A1_PHASE2_BATCH = 50       # 每批歸納幾篇摘要 → 主題
A1_GENERATE_N = 3 if SMOKE_TEST else 20   # 生成數
A1_MIN_DIM_SCORES = {"score_structural_depth": 5, "score_irreversibility": 5, "score_industry_relevance": 0, "score_topic_relevance": 0, "score_feasibility": 5}
A1_TOPIC_RELEVANCE_CAP = False   # If True: topic_relevance ≤ 3 → total_score capped at 15

# ─── Step B: Weak Signal Selection ───────────────────
B_INPUT_FILE = INPUT_DIR / "Weak signals 2026-02-25_073946.xlsx"
B_BATCH_SIZE = 25          # 每批評分幾筆（25: 平衡覆蓋率與呼叫次數）
B_TOP_N = 20 if SMOKE_TEST else 2000       # 精選數量
B_DIVERSITY_BATCH = 600    # 每批去重幾筆（避免單次 call 輸出截斷）
B_MIN_DIM_SCORES = {"outside_area": 5, "novelty": 5, "social_impact": 5, "topic_relevance": 0}
B_TOPIC_RELEVANCE_CAP = False    # If True: topic_relevance ≤ 3 → total_score capped at 15

# ─── Step C: Unexpected Scenarios ────────────────────
C_GENERATE_N = 5 if SMOKE_TEST else 150   # 生成數
C_MODE = "cluster"                         # "cluster" (k-means) or "random" (random grouping)
C_DIVERSITY_MAX_PCT = 40                   # Max % of final scenarios from a single theme
C_MIN_DIM_SCORES = {
    "score_unexpectedness": 5,
    "score_social_impact": 5,
    "score_uncertainty": 5,
}

# ─── Step D: Opportunity Scenarios ───────────────────
D_MODE = "hybrid"                          # "hybrid" (smart pair selection) or "random" (random A×C pairing)
D_GENERATE_N = 5 if SMOKE_TEST else 40    # hybrid: pairs to select
D_MIN_DIM_SCORES = {"collision_score": 0, "unexpected_score": 5, "impact_score": 5, "plausibility_score": 5, "topic_relevance_score": 0}
D_PLAUSIBILITY_PASSFAIL = True   # If True: plausibility is pass/fail (≥ threshold), not counted in total
D_TOPIC_RELEVANCE_CAP = False    # If True: topic_relevance_score ≤ 3 → total_score capped at 20
D_MATRIX_MODE = True             # If True: classify scenarios into Unexpectedness × Impact matrix


# ─── Project Context ─────────────────────────────────
TOPIC = "Aging Society（高齢化社会）"
TIMEFRAME = "Next 10-15 years"

# ─── Writing Style (shared across all generation prompts) ──
WRITING_STYLE = """\
# WRITING STYLE — Top Priority
These scenarios are workshop materials. Participants will scan them in seconds, so clarity beats completeness.
- Write like a sharp management consultant briefing a CEO: one idea per sentence, no filler, no jargon chains.
- Titles must be vivid and specific — the reader should picture a concrete scene, not an abstract concept. Good: "80-year-olds design their own towns." Bad: "Integrated elderly support platform initiative."
- Lead every paragraph with the punchline. Support with 1-2 concrete details, then stop.
- Favor surprising, counterintuitive angles over comprehensive coverage. The goal is to provoke "I never thought of that" — not to summarize everything we know.

# JAPANESE WRITING QUALITY — 日本語の書き方ルール
- 一文は60字以内を目安にする。読点（、）が3つ以上ある文は分割する。
- 名詞の連続（「高齢者支援型デジタル統合ケアプラットフォーム」のような漢字チェーン）は禁止。最長4漢字で区切り、助詞を入れて読みやすくする。
- 行政・学術用語をそのまま使わない。「地域包括ケアシステム」→「住み慣れた場所で医療・介護が受けられる仕組み」のように、仕組みを具体的に書く。
- 主語を省略しすぎない。誰が・何がを明示する。
- 体言止め（名詞で文を終える）は見出し以外では使わない。
- 数字は必ず半角アラビア数字を使う（×：二千五十七 → ○：2,057）。"""

CLIENT_PROFILE = {
    "name": "Client companies of JRI (Japan Research Institute) Mirai Design Lab",
    "description": (
        "Major Japanese corporations across diverse industries. "
        "Well-informed about trends in their own industries and related sectors, "
        "but have limited awareness of trends from unrelated fields and lifestyle changes abroad."
    ),
    "industries": [
        "Automotive",
        "Chemicals",
        "Electronics & Electrical Equipment",
        "Beverages",
        "ICT",
        "Materials",
        "Construction",
        "Trading companies",
    ],
    "industries_ja": [
        "自動車",
        "化学",
        "電機",
        "飲料",
        "ICT",
        "素材",
        "建設",
        "商社",
    ],
    "known_domains": [
        "Elderly care / nursing care",
        "Pension systems",
        "Rising medical costs",
        "Labor shortage",
        "Declining birthrate",
        "Care robots",
        "Healthy life expectancy",
        "Senior consumer market",
        "Social security reform",
        "Community-based integrated care",
    ],
}


# ─── UI-adjustable parameter definitions ────────────
# Maps param name → {section, label, type, min, max, default, options}
# Used by the Web UI to render controls and by apply_overrides to validate.

UI_PARAMS = {
    # Global
    "TOPIC":        {"section": "Global", "label": "主題 Topic",          "type": "text",   "default": TOPIC},
    "TIMEFRAME":    {"section": "Global", "label": "時間範圍 Timeframe",  "type": "text",   "default": TIMEFRAME},
    "INDUSTRIES":   {"section": "Global", "label": "產業列表 (comma-separated)", "type": "text", "default": ", ".join(CLIENT_PROFILE["industries"])},

    # A1
    "A1_GENERATE_N":                {"section": "A1 Expected", "label": "生成情境數",            "type": "number", "min": 5,  "max": 100, "default": 20},
    "A1_SCORE_STRUCTURAL_DEPTH":    {"section": "A1 Expected", "label": "門檻: Structural Depth", "type": "number", "min": 0,  "max": 10,  "default": 5},
    "A1_SCORE_IRREVERSIBILITY":     {"section": "A1 Expected", "label": "門檻: Irreversibility",  "type": "number", "min": 0,  "max": 10,  "default": 5},
    "A1_SCORE_INDUSTRY_RELEVANCE":  {"section": "A1 Expected", "label": "門檻: Industry Relevance","type": "number", "min": 0,  "max": 10,  "default": 0},
    "A1_SCORE_TOPIC_RELEVANCE":     {"section": "A1 Expected", "label": "門檻: Topic Relevance",  "type": "number", "min": 0,  "max": 10,  "default": 0},
    "A1_SCORE_FEASIBILITY":         {"section": "A1 Expected", "label": "門檻: Feasibility",      "type": "number", "min": 0,  "max": 10,  "default": 5},
    "A1_TOPIC_RELEVANCE_CAP":       {"section": "A1 Expected", "label": "Topic Relevance Cap 開關","type": "bool",   "default": False},

    # B
    "B_TOP_N":                      {"section": "B Weak Signal", "label": "篩選數量",              "type": "number", "min": 100, "max": 5000, "default": 2000},
    "B_SCORE_OUTSIDE_AREA":         {"section": "B Weak Signal", "label": "門檻: Outside Area",    "type": "number", "min": 0,   "max": 10,   "default": 5},
    "B_SCORE_NOVELTY":              {"section": "B Weak Signal", "label": "門檻: Novelty",         "type": "number", "min": 0,   "max": 10,   "default": 5},
    "B_SCORE_SOCIAL_IMPACT":        {"section": "B Weak Signal", "label": "門檻: Social Impact",   "type": "number", "min": 0,   "max": 10,   "default": 5},
    "B_SCORE_TOPIC_RELEVANCE":      {"section": "B Weak Signal", "label": "門檻: Topic Relevance", "type": "number", "min": 0,   "max": 10,   "default": 0},
    "B_TOPIC_RELEVANCE_CAP":        {"section": "B Weak Signal", "label": "Topic Relevance Cap 開關","type": "bool",  "default": False},

    # C
    "C_GENERATE_N":                 {"section": "C Unexpected", "label": "生成情境數",             "type": "number", "min": 5,  "max": 300, "default": 150},
    "C_MODE":                       {"section": "C Unexpected", "label": "分群模式",               "type": "select", "options": ["cluster", "random"], "default": "cluster"},
    "C_DIVERSITY_MAX_PCT":          {"section": "C Unexpected", "label": "單一主題上限 %",          "type": "number", "min": 10, "max": 100, "default": 40},
    "C_SCORE_UNEXPECTEDNESS":       {"section": "C Unexpected", "label": "門檻: Unexpectedness",   "type": "number", "min": 0,  "max": 10,  "default": 5},
    "C_SCORE_SOCIAL_IMPACT":        {"section": "C Unexpected", "label": "門檻: Social Impact",    "type": "number", "min": 0,  "max": 10,  "default": 5},
    "C_SCORE_UNCERTAINTY":          {"section": "C Unexpected", "label": "門檻: Uncertainty",      "type": "number", "min": 0,  "max": 10,  "default": 5},

    # D
    "D_GENERATE_N":                 {"section": "D Opportunity", "label": "配對數量",              "type": "number", "min": 5,  "max": 100, "default": 40},
    "D_MODE":                       {"section": "D Opportunity", "label": "配對模式",              "type": "select", "options": ["hybrid", "random"], "default": "hybrid"},
    "D_SCORE_COLLISION":            {"section": "D Opportunity", "label": "門檻: Collision",       "type": "number", "min": 0,  "max": 10,  "default": 0},
    "D_SCORE_UNEXPECTED":           {"section": "D Opportunity", "label": "門檻: Unexpected",      "type": "number", "min": 0,  "max": 10,  "default": 5},
    "D_SCORE_IMPACT":               {"section": "D Opportunity", "label": "門檻: Impact",          "type": "number", "min": 0,  "max": 10,  "default": 5},
    "D_SCORE_PLAUSIBILITY":         {"section": "D Opportunity", "label": "門檻: Plausibility",    "type": "number", "min": 0,  "max": 10,  "default": 5},
    "D_SCORE_TOPIC_RELEVANCE":      {"section": "D Opportunity", "label": "門檻: Topic Relevance", "type": "number", "min": 0,  "max": 10,  "default": 0},
    "D_TOPIC_RELEVANCE_CAP":        {"section": "D Opportunity", "label": "Topic Relevance Cap 開關","type": "bool",  "default": False},
    "D_MATRIX_MODE":                {"section": "D Opportunity", "label": "矩陣分類 (Unexpectedness × Impact)","type": "bool", "default": True},
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
