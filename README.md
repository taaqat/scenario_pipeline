# AI Scenario Pipeline (JRI × III Living Lab+)

未來情境分析自動化 Pipeline — 支援多題目切換。

詳細的 Streamlit 部署 / 操作指南見 [`STREAMLIT_GUIDE.md`](STREAMLIT_GUIDE.md)。

---

## Architecture

```
Articles ──→ [A1] Summarize(Haiku) → BERTopic Cluster + Label(Opus) → Generate(Opus) → Rank + pick_final(gpt-5.4) ──→ Expected Scenarios ──┐
                                                                                                                                              ├─→ [D] Random Pairing → Generate(Opus) → Rank + pick_final + Matrix(gpt-5.4) → Opportunity Scenarios
Weak Signals ──→ [B] Score(gpt-5.4) → Re-rank by weights → Diversity Dedup(gpt-5.4) ──→ Selected Signals ──→ [C] BERTopic Cluster + Label(Opus) → Generate(Opus) → Rank + pick_final(gpt-5.4) ──→ Unexpected Scenarios ──┘
```

關鍵點：
- A1 / C / D 由 UI 設定交付數 N，系統 over-generate `pool_n = min(N × overgen_factor, cap)` 個候選後 `pick_final` 選 top N
- B Phase 1 評分結果 cache 後可重用，改 weights / N 不會觸發重評
- D 讀取 A1 / C 的 output JSON（pick_final 後的最終版）做隨機 A×C 配對
- Cluster 用 **BERTopic（UMAP + HDBSCAN）**，LLM 負責命名
- 輸出只有日文版

---

## Setup

```bash
# 1. Python 3.13 venv
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Node.js 依賴（PPTX 產生用）
npm install

# 3. 環境變數
cp .env.example .env
# 然後編輯 .env，填入 ANTHROPIC_API_KEY 和 OPENAI_API_KEY
```

---

## Run

### Streamlit Web UI（部署主流）

```bash
streamlit run streamlit_app.py
# → http://localhost:8501
```

詳見 [`STREAMLIT_GUIDE.md`](STREAMLIT_GUIDE.md)（部署到 Streamlit Cloud 的設定也在裡面）。

### CLI

```bash
# 預設 topic（JRI 高齡化）
python run_pipeline.py

# 切換 topic
python run_pipeline.py --config configs/energy.py

# 跑單一步驟
python run_pipeline.py --step a1
python run_pipeline.py --step b
python run_pipeline.py --step c
python run_pipeline.py --step d

# A1 拆 phase 跑
python run_pipeline.py --step a1 --phase 1   # 摘要
python run_pipeline.py --step a1 --phase 2   # cluster
python run_pipeline.py --step a1 --phase 3   # 生成
python run_pipeline.py --step a1 --phase 4   # 排序 + pick_final
```

---

## Topic Configs

用 `--config` 切換題目，不需要改 code：

| Config | 題目 |
|---|---|
| `configs/jri_aging.py`（預設）| JRI 高齡化社會 |
| `configs/energy.py` | 電力永續 |

新增題目就在 `configs/` 加一個新的 `.py`。

---

## Data Preparation

輸入檔放進 `data/input/{topic_subdir}/`，檔名在對應的 topic config 裡定義（例如 `configs/jri_aging.py` 的 `A1_INPUT_FILE` 與 `B_INPUT_FILE`）。

---

## Models

| Step | Task | Model |
|------|------|-------|
| A1 Phase 1 | Article summarize | Claude Haiku 4.5 |
| A1 Phase 2 | BERTopic cluster labeling | Claude Opus 4.6 |
| A1 Phase 3 | Scenario generation | Claude Opus 4.6 |
| A1 Phase 4 | Ranking + pick_final | gpt-5.4 |
| B Phase 1 | Signal scoring | gpt-5.4 |
| B Phase 2 | Diversity dedup | gpt-5.4 |
| C Phase 1 | BERTopic cluster labeling | Claude Opus 4.6 |
| C Phase 2 | Scenario generation | Claude Opus 4.6 |
| C Phase 3 | Ranking + pick_final | gpt-5.4 |
| D Phase 2 | Opportunity generation | Claude Opus 4.6 |
| D Phase 3 | Ranking + pick_final | gpt-5.4 |
| Embedding | Clustering input | text-embedding-3-large (OpenAI) |

---

## Outputs

`data/output/{topic_subdir}/` 下：

| Deliverable | Files |
|---|---|
| Expected Scenarios | `A1_expected_scenarios_ja.json`, `.xlsx` |
| Selected Weak Signals | `B_selected_weak_signals_ja.json`, `.xlsx` |
| Unexpected Scenarios | `C_unexpected_scenarios_ja.json`, `.xlsx` |
| C scenarios referenced by D | `C_used_in_D_ja.json` |
| Opportunity Scenarios | `D_opportunity_scenarios_ja.json`, `.xlsx` |
| Cost report (per run) | `cost_report.json` |
| Cost report (cumulative) | `cost_report_cumulative.json` |
| PowerPoint deck | `JRI_Aging_Report_ja.pptx`（Streamlit Generate PPT 鈕） |

---

## Project Structure

```
scenario_pipeline/
├── README.md                       # 本檔
├── STREAMLIT_GUIDE.md              # Streamlit 部署 / 操作指南
├── .env.example                    # API key 範本
├── requirements.txt                # Python 依賴
├── packages.txt                    # Streamlit Cloud apt 依賴 (nodejs/npm)
├── package.json                    # Node 依賴 (pptxgenjs)
├── Dockerfile / docker-compose.yml # Docker 部署
├── start_streamlit.sh              # 本機啟動腳本
├── config.py                       # 全域設定 + UI_PARAMS + apply_overrides
├── streamlit_app.py                # Streamlit Web UI
├── run_pipeline.py                 # CLI 入口 + save_cost_report
├── generate_pptx.js                # PowerPoint 產生（Node）
├── .streamlit/config.toml          # Streamlit 配置
├── configs/
│   ├── jri_aging.py                # 預設 topic
│   └── energy.py                   # 範例 topic
├── prompts/                        # LLM prompt 模板
├── steps/                          # step_a1 / step_b / step_c / step_d
├── utils/                          # llm_client / openai_client / data_io / clustering / bilingual
└── data/                           # input / intermediate / output（皆 gitignored）
```
