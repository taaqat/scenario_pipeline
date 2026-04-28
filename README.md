# AI Scenario Pipeline

未來情境分析自動化 Pipeline — 支援多題目切換。

新接手的工程師請先讀 [`HANDOFF.md`](HANDOFF.md)。
詳細流程請看 [`pipeline_flow_document.md`](pipeline_flow_document.md)。

---

## Architecture

```
Articles ──→ [A1] Summarize(Haiku) → BERTopic Cluster + Label(Opus) → Generate(Opus) → Rank + pick_final(gpt-5.4) ──→ Expected Scenarios ──┐
                                                                                                                                              ├─→ [D] Pair Select(gpt-5.4) → Generate(Opus) → Rank + pick_final(gpt-5.4) → Opportunity Scenarios + Matrix
Weak Signals ──→ [B] Score(gpt-5.4) → Re-rank by weights → Diversity Dedup(gpt-5.4) ──→ Selected Signals ──→ [C] BERTopic Cluster + Label(Opus) → Generate(Opus) → Rank + pick_final(gpt-5.4) ──→ Unexpected Scenarios ──┘
```

關鍵點：
- A1 / C / D 由 UI 設定交付數 N，系統 over-generate `pool_n = min(N × overgen_factor, cap)` 個候選後 `pick_final` 選 top N
- B Phase 1 評分結果 cache 後可重用，改 weights / N 不會觸發重評
- D 讀取 A1 / C 的 output JSON（pick_final 後的最終版）做 A×C 配對
- Cluster 用 **BERTopic（UMAP + HDBSCAN）**，LLM 負責命名
- 預設只產出日文版；要中文翻譯把 `TRANSLATE_ENABLED=True` 並加回 UI toggle

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

### Web UI（NiceGUI）

```bash
python app.py
# → http://localhost:8080
# 預設帳密 jri / livinglab2026（部署前請改，見 HANDOFF.md）
```

### Streamlit Web UI（部署推薦）

```bash
# 方式 1：直接運行
streamlit run streamlit_app.py

# 方式 2：使用啟動腳本
./start_streamlit.sh

# 方式 3：Docker 部署
docker-compose up -d

# → http://localhost:8501
# 詳見 STREAMLIT_DEPLOY.md
```

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
| D Phase 1 | Pair selection | gpt-5.4 |
| D Phase 2 | Opportunity generation | Claude Opus 4.6 |
| D Phase 3 | Ranking + pick_final | gpt-5.4 |
| Embedding | Clustering input | text-embedding-3-small (OpenAI) |
| Translation (optional) | ja → zh | gpt-5 |

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
| PowerPoint deck | `JRI_Aging_Report_ja.pptx` (Web UI 按鈕生成) |

開啟 `TRANSLATE_ENABLED=True` 時會多出 `_zh.json` 對應檔。

---

## Project Structure

```
scenario_pipeline/
├── HANDOFF.md                      # 給接手工程師的部署指南（先讀這個）
├── README.md                       # 本檔
├── STREAMLIT_DEPLOY.md             # Streamlit 部署指南
├── pipeline_flow_document.md       # 流程說明書
├── CLAUDE_CODE_GUIDE.md            # Claude Code 操作 guide
├── .env.example                    # API key 範本
├── requirements.txt                # Python 依賴
├── package.json                    # Node 依賴 (pptxgenjs)
├── Dockerfile                      # Docker 部署配置
├── docker-compose.yml              # Docker Compose 配置
├── start_streamlit.sh              # Streamlit 啟動腳本
├── config.py                       # 全域設定 + UI_PARAMS + apply_overrides
├── app.py                          # NiceGUI Web UI
├── streamlit_app.py                # Streamlit Web UI
├── run_pipeline.py                 # CLI 入口 + save_cost_report
├── generate_pptx.js                # PowerPoint 產生（Node）
├── validate_output.py              # 輸出驗證
├── audit_pptx.py                   # PPTX 審查工具
├── run_smoke.py                    # End-to-end smoke test
├── test_checkpoint.py              # B Phase 1 cache 測試（沙箱模式）
├── .streamlit/
│   └── config.toml                 # Streamlit 配置
├── configs/
│   ├── jri_aging.py                # 預設 topic
│   └── energy.py                   # 範例 topic
├── prompts/                        # 13 個 LLM prompt 模板
├── steps/
│   ├── step_a1.py
│   ├── step_b.py
│   ├── step_c.py
│   └── step_d.py
├── utils/
│   ├── llm_client.py               # Claude wrapper + CostTracker
│   ├── openai_client.py            # OpenAI wrapper
│   ├── data_io.py                  # rank_and_select / pick_final / apply_scores
│   ├── clustering.py               # BERTopic + build_cluster_dicts
│   └── bilingual.py                # ja↔zh 翻譯與儲存
├── clients need/                   # JRI 客戶 spec 文件（修改 prompt 前必看）
│   ├── final_criteria_v2.md
│   ├── 20250509 LivingLab+JRI.pptx
│   └── (signed QUOTATION)*.pdf
└── data/
    ├── input/                      # 客戶提供的 Excel
    ├── intermediate/               # cache + checkpoint（git-ignored）
    └── output/                     # 最終產出（git-ignored）
```
