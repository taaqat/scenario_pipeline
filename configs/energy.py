"""
Topic config: Electricity Sustainability（電力永續）
Usage: python3 run_pipeline.py --config configs/energy.py

Note: This topic outputs in Traditional Chinese (zh-TW).
      Pipeline filenames still use _ja.json convention — content is Chinese.
"""
from pathlib import Path

# ─── Project Context ─────────────────────────────────
TOPIC = "電力永續與智慧生活"
TIMEFRAME = "未來 10-15 年"
OUTPUT_LANGUAGE = "繁體中文"

# ─── Output & Input ─────────────────────────────────
OUTPUT_SUBDIR = "energy"
A1_INPUT_FILE = "electricity_articles.xlsx"
B_INPUT_FILE = "weak_signals_energy.xlsx"

# ─── Generation Counts (smaller dataset) ─────────────
A1_GENERATE_N = 10
B_TOP_N = 500
C_GENERATE_N = 50
D_GENERATE_N = 20

# ─── Writing Style ──────────────────────────────────
# Override the default Japanese writing style with Chinese version.
# When WRITING_STYLE is set directly, load_topic_config uses it as-is.
WRITING_STYLE_GOOD_EXAMPLE = '"廢棄礦坑變成電網最大的電池。"'
WRITING_STYLE_BAD_EXAMPLE = '"整合性永續能源平台推動方案。"'
JARGON_EXAMPLE_BEFORE = "「分散式能源資源整合管理基盤」"
JARGON_EXAMPLE_AFTER = "「把家家戶戶的太陽能和儲能電池串起來，互相調度電力的機制」"

WRITING_STYLE = """\
# 寫作風格 — 最高優先
這些情境是工作坊素材。參加者幾秒內就會掃過，所以清楚比完整重要。
- 像一個犀利的管理顧問在向 CEO 簡報：一句話一個重點，不灌水，不堆術語。
- 標題要生動具體——讀者看到就能想像一個畫面，而不是抽象概念。好：「廢棄礦坑變成電網最大的電池。」壞：「整合性永續能源平台推動方案。」
- 每段先講結論，用 1-2 個具體細節支撐，然後停。
- 偏好意外的、反直覺的角度，而非面面俱到。目標是讓人「我從沒想過這個」——而不是把已知的事摘要一遍。

# 繁體中文寫作品質規則
- 一句話以 40 字為上限。逗號超過 3 個就要拆句。
- 禁止名詞堆疊（「高齡者支援型數位整合照護平台」這類漢字連鎖）。最長 4 個漢字就斷開，加上助詞讓人讀得下去。
- 不要直接搬行政或學術用語。「分散式能源資源整合管理基盤」→「把家家戶戶的太陽能和儲能電池串起來，互相調度電力的機制」。用白話解釋機制。
- 主詞不要省略太多。誰做了什麼要寫清楚。
- 數字一律用半形阿拉伯數字（×：兩千零五十七 → ○：2,057）。
- 使用繁體中文，不要使用簡體中文或日文。"""

# ─── Client Profile ──────────────────────────────────
CLIENT_PROFILE = {
    "name": "電力與永續領域的企業",
    "description": (
        "能源及相關產業的企業。"
        "熟悉主流能源趨勢與現行法規，"
        "但尋求意想不到的情境與跨產業機會。"
    ),
    "industries": [
        "電力與公用事業",
        "再生能源",
        "電網基礎設施",
        "儲能與電池",
        "智慧電網與 IoT",
        "電動車與移動服務",
        "重工業（鋼鐵、化工）",
        "不動產與營建",
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
        "太陽能與風力發電",
        "核能重啟政策",
        "2050 碳中和目標",
        "電網穩定與尖峰管理",
        "躉購費率（FIT/FIP）制度",
        "電力市場自由化",
        "鋰電池技術",
        "電動車充電基礎設施",
        "氫能與混氨發電",
        "企業購電協議與 RE100",
    ],
}
