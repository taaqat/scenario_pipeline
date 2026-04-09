"""
Topic config: Electricity Sustainability（電力の持続可能性）
Usage: python3 run_pipeline.py --config configs/energy.py
"""
from pathlib import Path

# ─── Project Context ─────────────────────────────────
TOPIC = "Electricity Sustainability（電力の持続可能性）"
TIMEFRAME = "Next 10-15 years"

# ─── Input Files ─────────────────────────────────────
A1_INPUT_FILE = "electricity_articles.xlsx"
B_INPUT_FILE = "weak_signals_energy.xlsx"

# ─── Generation Counts (smaller dataset) ─────────────
A1_GENERATE_N = 10
B_TOP_N = 500
C_GENERATE_N = 50
D_GENERATE_N = 15

# ─── Writing Style Examples ──────────────────────────
WRITING_STYLE_GOOD_EXAMPLE = '"Abandoned mines become the grid\'s biggest battery."'
WRITING_STYLE_BAD_EXAMPLE = '"Integrated sustainable energy platform initiative."'
JARGON_EXAMPLE_BEFORE = "「分散型エネルギーリソース統合管理基盤」"
JARGON_EXAMPLE_AFTER = "「家庭の太陽光と蓄電池を束ねて電力を融通する仕組み」"

# ─── Client Profile ──────────────────────────────────
CLIENT_PROFILE = {
    "name": "Energy sector companies exploring sustainable electricity futures",
    "description": (
        "Companies in the energy and related industries. "
        "Well-informed about mainstream energy trends and current regulations, "
        "but seeking unexpected scenarios and cross-industry opportunities."
    ),
    "industries": [
        "Electric Power & Utilities",
        "Renewable Energy",
        "Grid Infrastructure",
        "Energy Storage & Batteries",
        "Smart Grid & IoT",
        "EV & Mobility",
        "Heavy Industry (Steel, Chemicals)",
        "Real Estate & Construction",
    ],
    "industries_ja": [
        "電力・ユーティリティ",
        "再生可能エネルギー",
        "送配電インフラ",
        "蓄電池・エネルギー貯蔵",
        "スマートグリッド・IoT",
        "EV・モビリティ",
        "重工業（鉄鋼・化学）",
        "不動産・建設",
    ],
    "known_domains": [
        "Solar and wind power generation",
        "Nuclear energy restart policy",
        "Carbon neutrality 2050 targets",
        "Grid stability and peak demand management",
        "Feed-in tariff (FIT/FIP) systems",
        "Electricity market deregulation",
        "Lithium-ion battery technology",
        "EV charging infrastructure",
        "Hydrogen energy and ammonia co-firing",
        "Corporate PPA and RE100",
    ],
}
