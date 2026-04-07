# JRI Living Lab+ AI Scenario Pipeline — Claude Code 版

## 使用方式
把這份文件丟給 Claude Code，告訴它「照著這個 guide 執行 Step X」。
每個 Step 可以獨立執行，中間產物存在 `data/intermediate/`。

目前流程的核心原則：
- A1、C、D 沒有硬性的交付數上限，輸出所有通過 gate filter 的情境
- A1、C、D 在評分後都會再跑一次全域 `llm_review`
- D 讀的是人工篩選後的 A1 / C 輸出，不是原始全量候選

---

## 前置作業

```bash
# 1. 把資料放到 data/input/
#    - 日本 JRI aging 7240 rows.xlsx
#    - Weak signals 2026-02-25_073946.xlsx
# 2. 設定環境變數
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

---

## Step A-1: Expected Scenarios（預期情境）

### 執行

```bash
python3 run_pipeline.py --step a1

# 或分階段：
python3 run_pipeline.py --step a1 --phase 1  # 摘要（Haiku）
python3 run_pipeline.py --step a1 --phase 2  # K-Means 分群 + Opus 標記主題
python3 run_pipeline.py --step a1 --phase 3  # 生成候選（Opus）
python3 run_pipeline.py --step a1 --phase 4  # 評分 + gate filter + global review（gpt-5.2）
```

### 流程
1. 讀取 7240 篇日文文章
2. Phase 1: 每 10 篇一批，用 Claude Haiku 做摘要 → `a1_phase1_summaries.json`
3. Phase 2: 用 embedding + K-Means 聚成約 36 個 themes，再由 Claude Opus 做群組標記 → `a1_phase2_themes.json`
4. Phase 3: 每個 theme 生成 1 個 Expected Scenario 候選 → `a1_phase3_scenarios.json`
5. Phase 4: 用 gpt-5.2 依 4 個維度評分，套用每維最低分門檻，再做全域 review → `a1_phase4_ranked.json` + output

### 輸出
- `data/output/A1_expected_scenarios_ja.json`
- `data/output/A1_expected_scenarios_zh.json`
- `data/output/A1_expected_scenarios.xlsx`

---

## Step B: Weak Signal Selection（弱訊號篩選）

### 執行

```bash
python3 run_pipeline.py --step b
```

### 流程
1. 讀取弱訊號資料庫（9000+ 筆）
2. Phase 1: 每 25 筆一批，用 gpt-5.2 做四維度評分 → `b_phase1_scored.json`
3. Phase 2: 按總分排序，取前 3000 筆候選 → `b_phase2_top3000_candidates.json`
4. Phase 3: 分批用 gpt-5.2 做多樣性去重，保留 2000 筆，翻譯為繁中 → output

### 輸出
- `data/output/B_selected_weak_signals_ja.json`
- `data/output/B_selected_weak_signals_zh.json`
- `data/output/B_selected_weak_signals.xlsx`

---

## Step C: Unexpected Scenarios（非預期情境）

### 執行

```bash
python3 run_pipeline.py --step c
```

### 前置條件
- Step B 結果已存在 `data/intermediate/b_phase3_dedup_selected.json`

### 流程
1. 讀取 B 篩選後的 2000 筆弱訊號
2. Phase 1: 用 embedding + K-Means 聚成 150 個群組，再由 Claude Opus 做群組標記 → `c_phase1_clusters.json`
3. Phase 2: 每個群組生成 1 個 Unexpected Scenario，生成 prompt 內含 Source Signal Integrity HARD GATE → `c_phase2_scenarios.json`
4. Phase 3: 用 gpt-5.2 依 3 個維度評分，套用每維最低分門檻，再做全域 review → output

### 輸出
- `data/output/C_unexpected_scenarios_ja.json`
- `data/output/C_unexpected_scenarios_zh.json`
- `data/output/C_unexpected_scenarios.xlsx`

---

## Step D: Opportunity Scenarios（機會情境）

### 執行

```bash
python3 run_pipeline.py --step d
```

### 前置條件
- `data/output/A1_expected_scenarios_ja.json`
- `data/output/C_unexpected_scenarios_ja.json`

這兩份通常會先經過人工篩選，再作為 D 的輸入。後續步驟以目前的 JSON 輸出為準。

### 流程
1. 讀取 A 和 C 輸出
2. Phase 1: 依 `cfg.D_MODE` 做 pair selection。預設是 `hybrid`，由 Claude Opus 挑出約 40 組最值得碰撞的 pairs
3. Phase 2: 每組 pair 生成 1 個 Opportunity Scenario，prompt 內要求 commercial viability
4. Phase 3: 用 gpt-5.2 依 5 個維度評分，套用每維最低分門檻，再做全域 review → output

### 輸出
- `data/output/D_opportunity_scenarios_ja.json`
- `data/output/D_opportunity_scenarios_zh.json`
- `data/output/D_opportunity_scenarios.xlsx`
- `data/output/C_used_in_D_ja.json`
- `data/output/C_used_in_D_zh.json`

---

## 重新評分 / 人工篩選

```bash
# 重新跑既有候選池的 ranking / gate / review
python3 rerank.py A
python3 rerank.py C --limit 100
python3 rerank.py D --no-translate
```

---

## PPTX 報告生成

### 前置條件
- A/C/D 的 output 已存在

### 執行
```bash
npm install
node generate_pptx.js
```

### 輸出
- `data/output/MVP_Report_ja.pptx`
- `data/output/MVP_Report_zh.pptx`

---

## 全流程一次跑完

```bash
python3 run_pipeline.py
```

---

## 目前重要輸出檔案

```
data/output/
├── A1_expected_scenarios_ja.json
├── A1_expected_scenarios_zh.json
├── A1_expected_scenarios.xlsx
├── B_selected_weak_signals_ja.json
├── B_selected_weak_signals_zh.json
├── B_selected_weak_signals.xlsx
├── C_unexpected_scenarios_ja.json
├── C_unexpected_scenarios_zh.json
├── C_unexpected_scenarios.xlsx
├── C_used_in_D_ja.json
├── C_used_in_D_zh.json
├── C_used_in_D.xlsx
├── D_opportunity_scenarios_ja.json
├── D_opportunity_scenarios_zh.json
├── D_opportunity_scenarios.xlsx
└── cost_report.json

data/intermediate/
├── a1_phase1_summaries.json
├── a1_phase2_themes.json
├── a1_phase3_scenarios.json
├── a1_phase4_ranked.json
├── b_phase1_scored.json
├── b_phase2_top3000_candidates.json
├── b_phase3_dedup_selected.json
├── b_phase3_dedup_summary.json
├── c_phase1_clusters.json
├── c_phase2_scenarios.json
├── d_phase1_pairs.json
└── d_phase2_scenarios.json
```

---

## 注意事項

1. 每個主要 phase 都有 checkpoint，中途中斷後可續跑
2. 所有 prompt 在 `prompts/`，改完直接重跑對應 phase 即可
3. 在 `config.py` 設 `SMOKE_TEST = True` 可用少量資料快速測試流程
4. 每次跑完會更新 `data/output/cost_report.json`
