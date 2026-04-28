# JRI Living Lab+ AI Scenario Pipeline — Claude Code 版

## 使用方式
把這份文件丟給 Claude Code，告訴它「照著這個 guide 執行 Step X」。
每個 Step 可以獨立執行，中間產物存在 `data/intermediate/{topic_subdir}/`。

目前流程的核心原則：
- A1、C、D 各自由 UI 設定 `*_GENERATE_N`（最終交付數），系統 over-generate `pool_n` 個候選後 `pick_final` 選 top N
- 評分後 `pick_final` 一次 LLM call 做 diversity 去重 + title 改寫；舊的 `llm_review` 已退役
- D 讀的是 A1 / C 的 OUTPUT 檔（pick_final 後）做 A×C 配對
- Cluster 一律用 BERTopic（OpenAI embedding → UMAP → HDBSCAN），LLM 負責命名

---

## 前置作業

```bash
# 1. 把資料放到 data/input/jri_aging/
#    - 日本 JRI aging 7240 rows.xlsx       （客戶 deliverable PPT 上是 6,135 件）
#    - Weak signals 2026-02-25_073946.xlsx  （9,004 件）
# 2. 設定環境變數
cp .env.example .env
# 編輯 .env，填入 ANTHROPIC_API_KEY 和 OPENAI_API_KEY
```

---

## Step A-1: Expected Scenarios（預期情境）

### 執行

```bash
python run_pipeline.py --step a1

# 或分階段：
python run_pipeline.py --step a1 --phase 1  # 摘要（Claude Haiku）
python run_pipeline.py --step a1 --phase 2  # BERTopic 分群 + Opus 標記主題
python run_pipeline.py --step a1 --phase 3  # 生成候選（Opus）
python run_pipeline.py --step a1 --phase 4  # 評分 + pick_final（gpt-5.4）
```

### 流程
1. 讀取輸入文章
2. Phase 1: 每 10 篇一批，用 Claude Haiku 4.5 做摘要 → `a1_phase1_summaries.json`（有 checkpoint）
3. Phase 2: OpenAI embedding → UMAP 降維 → HDBSCAN 分群 → Claude Opus 4.6 做群組命名 → `a1_phase2_themes.json`
4. Phase 3: 每個 theme 生成 1 個 Expected Scenario 候選 → `a1_phase3_scenarios.json`（有 checkpoint）
5. Phase 4: 用 gpt-5.4 依 5 個維度評分（structural_depth / irreversibility / industry_related / topic_relevance / feasibility）→ pick_final 選 top N + 改寫 title → output

### 輸出
- `data/output/{topic_subdir}/A1_expected_scenarios_ja.json`
- `data/output/{topic_subdir}/A1_expected_scenarios.xlsx`
- 若 `TRANSLATE_ENABLED=True`：另出 `_zh.json`

---

## Step B: Weak Signal Selection（弱訊號篩選）

### 執行

```bash
python run_pipeline.py --step b
```

### 流程
1. 讀取弱訊號 Excel（~9,000 筆）
2. Phase 1: 每 25 筆一批，用 gpt-5.4 做 3 維度評分（outside_area / novelty / social_impact）→ `b_phase1_scored.json`（最貴的一步、有 checkpoint）
3. Phase 2: 用 `B_WEIGHTS` 重算 total_score → 排序取 top `B_TOP_N × 1.5` → 分批用 gpt-5.4 做多樣性去重 → trim 到 `B_TOP_N` → output

### 輸出
- `data/output/{topic_subdir}/B_selected_weak_signals_ja.json`
- `data/output/{topic_subdir}/B_selected_weak_signals.xlsx`

### Cache 行為（重要）
- Phase 1 cache 只看：input 檔 mtime / prompt / topic / client_profile / model
- 改 `B_TOP_N` 或 `B_WEIGHTS` **不會**觸發 Phase 1 重評（Phase 2 才重跑）
- 改 prompt / topic / industries / Excel 檔內容 → Phase 1 全重跑（~20 分鐘、~\$25）

---

## Step C: Unexpected Scenarios（非預期情境）

### 執行

```bash
python run_pipeline.py --step c
```

### 前置條件
- Step B 結果已存在 `data/intermediate/{topic_subdir}/b_phase3_dedup_selected.json`

### 流程
1. 讀取 B 篩選後的弱訊號
2. Phase 1: 依 `C_MODE` 分群（`cluster_pair` 預設—BERTopic 後做主題碰撞 / `cluster` 單純分群 / `signal_pair` 跳過分群隨機配對）→ Claude Opus 命名 → `c_phase1_clusters.json`
3. Phase 2: 每個 cluster 生成 1 個 Unexpected Scenario（Title / Overview / WHY / WHO / WHERE / WHAT-HOW / 2020-2030-2040 timeline）→ `c_phase2_scenarios.json`（有 checkpoint）
4. Phase 3: 用 gpt-5.4 依 3 個維度評分（unexpectedness / social_impact / uncertainty）→ pick_final 選 top N → output

### 輸出
- `data/output/{topic_subdir}/C_unexpected_scenarios_ja.json`
- `data/output/{topic_subdir}/C_unexpected_scenarios.xlsx`

---

## Step D: Opportunity Scenarios（機會情境）

### 執行

```bash
python run_pipeline.py --step d
```

### 前置條件
- `data/output/{topic_subdir}/A1_expected_scenarios_ja.json`
- `data/output/{topic_subdir}/C_unexpected_scenarios_ja.json`

### 流程
1. 讀取 A1 和 C 的 output JSON（pick_final 後的最終版）
2. Phase 1: 依 `D_MODE` 做 pair selection（`select_pairs` LLM 智能配對 / `random` 隨機 / `matrix` 全窮舉 N_A × N_C）→ `d_phase1_pairs.json`（有 freshness check）
3. Phase 2: 每組 pair 生成 1 個 Opportunity Scenario（Title / Background / About the Future / Implications / Approach / Transformation Points）→ `d_phase2_scenarios.json`（有 checkpoint）
4. Phase 3: 用 gpt-5.4 依 3 個 weighted dim 評分（unexpected_score / impact_score / plausibility_score；plausibility 從 2026-04-27 起改成 weighted dim，不是 gate）→ pick_final 選 top N → 若 `D_MATRIX_MODE` 開啟還會分 4 quadrant → output

### 輸出
- `data/output/{topic_subdir}/D_opportunity_scenarios_ja.json`
- `data/output/{topic_subdir}/D_opportunity_scenarios.xlsx`
- `data/output/{topic_subdir}/C_used_in_D_ja.json`（D 引用到的 C scenarios 子集）

---

## PPTX 報告生成

### 前置條件
- A1 / C / D 的 output 已存在
- `npm install` 已完成

### 執行
```bash
node generate_pptx.js
# 或在 Web UI Results tab 按 Generate PPT
```

### 輸出
- `data/output/{topic_subdir}/JRI_Aging_Report_ja.pptx`

---

## 全流程一次跑完

```bash
python run_pipeline.py
# 預設跑 jri_aging topic；要切換用 --config configs/energy.py
```

---

## 注意事項

1. 每個主要 phase 都有 checkpoint，中途中斷後可續跑（A1 Phase 1/3、B Phase 1、C Phase 2、D Phase 2）
2. 所有 prompt 在 `prompts/`，改 prompt 通常會讓 signature 失效，下次 run 會重跑整個 phase
3. 在 `config.py` 設 `SMOKE_TEST = True` 可用少量資料快速測試流程
4. 每次跑完會更新 `data/output/{topic_subdir}/cost_report.json`（**只記當次 run**，每次 reset，不累計）
5. Web UI（`python app.py`）的 Run dialog 有「Generate new results」checkbox，勾起來會清掉本 step 的中間檔強制重生（保護 A1 摘要 + B 評分這兩個貴的 cache）
