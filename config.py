"""
JRI Living Lab+ AI Scenario Pipeline — Configuration
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
A1_MIN_DIM_SCORES = {"score_structural_depth": 5, "score_irreversibility": 5, "score_industry_relevance": 5, "score_topic_relevance": 5}

# ─── Step B: Weak Signal Selection ───────────────────
B_INPUT_FILE = INPUT_DIR / "Weak signals 2026-02-25_073946.xlsx"
B_BATCH_SIZE = 25          # 每批評分幾筆（25: 平衡覆蓋率與呼叫次數）
B_TOP_N = 20 if SMOKE_TEST else 2000       # 精選數量
B_DIVERSITY_BATCH = 600    # 每批去重幾筆（避免單次 call 輸出截斷）
B_MIN_DIM_SCORES = {"outside_area": 5, "novelty": 5, "social_impact": 5, "topic_relevance": 5}

# ─── Step C: Unexpected Scenarios ────────────────────
C_GENERATE_N = 5 if SMOKE_TEST else 150   # 生成數
C_MIN_DIM_SCORES = {
    "score_unexpectedness": 5,
    "score_social_impact": 5,
    "score_uncertainty": 5,
}

# ─── Step D: Opportunity Scenarios ───────────────────
D_MODE = "hybrid"                          # "hybrid" (smart pair selection) or "matrix" (forced A×C all pairs)
D_GENERATE_N = 5 if SMOKE_TEST else 40    # hybrid: pairs to select
D_MIN_DIM_SCORES = {"plausibility_score": 5, "impact_score": 5, "topic_relevance_score": 5, "collision_score": 5, "unexpected_score": 5}


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
