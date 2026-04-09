"""
Topic config: JRI Aging Society（高齢化社会）
Usage: python3 run_pipeline.py --config configs/jri_aging.py
"""
from pathlib import Path

# ─── Project Context ─────────────────────────────────
TOPIC = "Aging Society（高齢化社会）"
TIMEFRAME = "Next 10-15 years"

# ─── Input Files ─────────────────────────────────────
A1_INPUT_FILE = "日本 JRI aging 7240 rows.xlsx"
B_INPUT_FILE = "Weak signals 2026-02-25_073946.xlsx"

# ─── Generation Counts ───────────────────────────────
A1_GENERATE_N = 20
B_TOP_N = 2000
C_GENERATE_N = 150
D_GENERATE_N = 40

# ─── Writing Style Examples ──────────────────────────
WRITING_STYLE_GOOD_EXAMPLE = '"80-year-olds design their own towns."'
WRITING_STYLE_BAD_EXAMPLE = '"Integrated elderly support platform initiative."'
JARGON_EXAMPLE_BEFORE = "「地域包括ケアシステム」"
JARGON_EXAMPLE_AFTER = "「住み慣れた場所で医療・介護が受けられる仕組み」"

# ─── Client Profile ──────────────────────────────────
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
