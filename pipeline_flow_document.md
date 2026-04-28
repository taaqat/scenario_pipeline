# JRI Living Lab+ AI 情境分析管線

## 資料處理與分析流程說明書（2026-04-27 更新）

---

## 一、管線總覽

本管線將大量日文新聞與弱訊號，透過 AI 分析轉化為三類情境報告，最終產出商機。整體分為四步：

| 步驟 | 名稱 | 輸入 | 預設交付數 (UI 可調) |
|------|------|------|----------|
| A1 | 預期情境 (Expected) | 新聞資料庫（約 7,200 篇） | 10（min 5 / max 30）|
| B | 弱訊號篩選 (Weak Signal) | 弱訊號資料庫（約 9,000 條） | 2,000（min 100 / max 2,000）|
| C | 意外情境 (Unexpected) | B 篩選出的弱訊號 | 10（min 5 / max 100）|
| D | 商機情境 (Opportunity) | A1 × C 交叉配對 | 10（min 5 / max 30）|

**依賴關係**

```
Articles.xlsx → A1 ─┐
                    ├→ D
Signals.xlsx  → B → C ┘
```

- A1 獨立（只看 Articles.xlsx）
- B 獨立（只看 Signals.xlsx）— 與 A1 解耦（2026-04-27 起，B 評分不再參考 A1 排除主題）
- C 依賴 B 的輸出
- D 依賴 A1 + C 的最終輸出（OUTPUT_DIR 中的 json）

**關鍵原則**

- A1、C、D 系統 over-generate `pool_n = min(N × OVERGEN_FACTOR, CAP)` 個候選，再用 `pick_final` 一次 LLM call 選出 top N（diversity + title 改寫）
- B Phase 1 LLM 評分結果 cache 後可重複利用；改 weights / N / 跑 C 都不會觸發 B 重新評分
- D 的 3 個維度（unexpected / impact / plausibility）全部都是 weighted dim，沒有 pass/fail gate
- 所有 cluster 用 **BERTopic（OpenAI embedding + UMAP + HDBSCAN）**，LLM 負責命名

---

## 二、名詞定義

### 情境類型

- **A1 Expected**：產業在未來 ~10-15 年的結構性、不可逆變化
- **C Unexpected**：意料之外、社會性影響大、高不確定性的情境
- **D Opportunity**：A × C 交集帶出的企業商機

### 技術名詞

- **BERTopic**：clustering pipeline = OpenAI embedding → UMAP 降維 → HDBSCAN 密度分群。比 k-means 更擅長產生大小不均的 cluster（主流大群 + 小眾專題群 + outlier 池）
- **pool_n / pick_final**：over-generation 機制。先生 pool_n 個候選 → 排序加權 → pick_final 一次 LLM call 選 top N + 改寫差的 title
- **rank_and_select**：批次打分 → 加權排序，無門檻過濾
- **checkpoint**：A1 Phase 1/3、B Phase 1、C Phase 2、D Phase 2 支援斷點續跑；signature 變了 → 失效

---

## 三、步驟 A1：預期情境產生

**輸入**：`config.A1_INPUT_FILE`（Excel）→ **輸出**：`A1_expected_scenarios_{ja,zh}.json` + `.xlsx`

### Phase 1：文章摘要

- **輸入**：原始 Excel 文章（每批 `A1_PHASE1_BATCH = 10` 篇）
- **Model**：claude-haiku-4-5
- **Prompt**：`a1_phase1_summarize.txt`
- **輸出**：`a1_phase1_summaries.json`（檔案 + checkpoint）
- **Cache 失效**：input 檔變動 / prompt 變動

### Phase 2：主題聚合（BERTopic）

- **輸入**：Phase 1 全部摘要
- **演算法**：OpenAI embedding → UMAP（5 維、cosine、seed=42）→ HDBSCAN（`min_cluster_size = A1_BERTOPIC_MIN_CLUSTER_SIZE = 30`）→ optional `reduce_topics(target_n_topics=pool_n)`
- **Outliers**：`A1_BERTOPIC_DROP_OUTLIERS = True`（HDBSCAN 認為不夠密集的文章直接捨棄，避免污染 LLM 命名）
- **LLM 命名**：`a1_phase2_label_themes.txt`（Claude Opus 4.6）每群命主題名 + structural direction
- **輸出**：`a1_phase2_themes.json`
- **Cache**：每次重跑（無 cache，但便宜）

### Phase 3：情境產生

- **輸入**：Phase 2 主題群 + 每群代表文章（≤12 篇）
- **Model**：claude-opus-4-6
- **Prompt**：`a1_phase3_generate.txt`
- **輸出 fields**（每個 scenario）：
  - `title_ja`、`change_from_keyword_ja`、`change_to_keyword_ja`、`change_from_ja`、`change_to_ja`
  - `supporting_evidences_ja`（客戶原 *Hypothesis and Background*）
  - `post_change_scenario_ja`、`implications_for_company_ja`
- **輸出**：`a1_phase3_scenarios.json` + checkpoint
- **Cache 失效**：themes signature 變動

### Phase 4：評分 + diversity 選取

- **Model**：gpt-5（`cfg.RANK_MODEL`）
- **5 個評分維度**（`a1_phase4_rank.txt`）：

| Dim | 來源 | 說明 |
|---|---|---|
| `structural_depth` | 🟢 客戶原始 | 結構性程度 |
| `irreversibility` | 🟢 客戶原始 | 不可逆性 |
| `industry_related` | 🟢 客戶原始 | 與目標產業核心流程的關聯 |
| `topic_relevance` | ➕ 我們加的 | 與專案主題（如 Aging Society）的關聯 |
| `feasibility` | 🟢 客戶原始（語意調整）| 10-15 年內實現可能性 |

- `weighted_score = Σ (A1_WEIGHTS[dim] × dim_score)`
- `pick_final` 一次 LLM call 從 pool_n 中選 top N + 改寫太抽象的 title
- 若 `TRANSLATE_ENABLED`：再做 ja→zh 翻譯
- **輸出**：`A1_expected_scenarios_{ja,zh}.json` + `.xlsx`

---

## 四、步驟 B：弱訊號篩選

**輸入**：`config.B_INPUT_FILE`（Excel） → **輸出**：`B_selected_weak_signals_{ja,zh}.json` + `.xlsx`

### Phase 1：多維度評分

- **輸入**：原始 Excel 弱訊號（每批 `B_BATCH_SIZE = 25` 條）
- **Model**：gpt-5
- **Prompt**：`b_phase1_score_signals.txt`（**不含** A1 內容，2026-04-27 起獨立）
- **3 個維度**（全部客戶原始）：

| Dim | 說明 |
|---|---|
| `outside_area` | 是否在客戶熟悉的產業 / known_domains 之外 |
| `novelty` | 是否為客戶聞所未聞的新資訊 |
| `social_impact` | 對社會的潛在影響 |

- **輸出**：`b_phase1_scored.json`（cache 永久保存 per-dim 分數）+ checkpoint
- **Cache 失效**：input 檔 mtime / prompt / topic / client_profile / model 任一變

### Phase 2：加權排序 + diversity 去重

- **重新計算 total_score**：`Σ (B_WEIGHTS[dim] × dim_score)` — 改 weights 不重評分，只重排序（便宜）
- 排序後取 top `B_TOP_N × 1.5` 候選送 diversity check
- **Model**：gpt-5（`b_phase3_diversity_check.txt`）
- 每批 ≤`B_DIVERSITY_BATCH = 600` 條，LLM 標近似群、保留每群一條
- 最終 trim 到 `B_TOP_N` 條（預設 2000）
- **輸出**：`b_phase3_dedup_selected.json` + `.xlsx`
- **Cache**：無，每次重跑（但 LLM call 數少）

---

## 五、步驟 C：意外情境產生

**輸入**：B 的輸出 → **輸出**：`C_unexpected_scenarios_{ja,zh}.json` + `.xlsx`

### Phase 1：弱訊號聚類

3 種 mode（`config.C_MODE`）：

| Mode | 描述 |
|---|---|
| `cluster` | BERTopic 直接分群（最穩、單主題情境）|
| `cluster_pair`（**預設**）| BERTopic 後，每對隨機抽 3 組候選、保留 cosine 距離最遠的 → 強制跨主題碰撞 |
| `signal_pair` | 跳過 clustering，每群隨機 2 條 signal → 最混亂、原料碰撞 |

- BERTopic 配置：`C_BERTOPIC_MIN_CLUSTER_SIZE = 15`（小於 A1 因為 signal 短）
- LLM 命名：`c_phase1_label_clusters.txt`（claude-opus-4-6）
- **輸出**：`c_phase1_clusters.json`

### Phase 2：情境產生

- **Model**：claude-opus-4-6
- **Prompt**：`c_phase2_generate.txt`
- **輸出 fields**（每個 scenario）：
  - `title_ja`、`overview_ja`、`why_ja` (list)、`who_ja` (list)、`where_ja`、`what_how_ja` (list)
  - `source_signals`（signal IDs）
  - `timeline_decade`、`timeline_description_ja`（2030 / 2040 焦點）
- **輸出**：`c_phase2_scenarios.json` + checkpoint
- **Cache 失效**：clusters signature 變動

### Phase 3：評分 + diversity 選取

- **Model**：gpt-5
- **3 個維度（全部客戶原始）**：`unexpectedness`、`social_impact`、`uncertainty`
- `weighted_score = Σ C_WEIGHTS × dim_score` → `pick_final` 選 top `C_GENERATE_N`
- `pick_final` 用 `topic=""`（C 刻意跟主題解耦，由 signal 自身定義領域）
- **輸出**：`C_unexpected_scenarios_{ja,zh}.json` + `.xlsx`

---

## 六、步驟 D：商機情境產生

**輸入**：`A1_expected_scenarios_ja.json` + `C_unexpected_scenarios_ja.json`（OUTPUT_DIR）→ **輸出**：`D_opportunity_scenarios_{ja,zh}.json` + `C_used_in_D_{ja,zh}.json` + `.xlsx`

### Phase 1：A × C 配對

3 種 mode：

| Mode | 描述 |
|---|---|
| `select_pairs`（LLM-guided）| LLM 從 A × C 全集中選 16 對最有意義的（每對至少 1A + 2C）|
| `random` | 隨機抽 1A + 2C 配 16 對 |
| `matrix` | 窮舉 N_A × N_C（如 20 × 15 = 300 對）|

- **freshness check**：A/C output 檔 mtime > pairs.json mtime → 重新配對
- **輸出**：`d_phase1_pairs.json`

### Phase 2：商機報告產生

- **Model**：claude-opus-4-6
- **Prompt**：`d_phase2_generate.txt`
- **輸出 fields**：
  - `opportunity_title_ja`、`background_ja`、`about_the_future_ja`
  - `implications_for_company_ja`（含 [Opportunity] / [Challenge]）
  - `company_approach_ja`（含 [Industry] tag + 多階段子措施）
  - `transformation_points_ja`
  - `selected_expected` / `selected_unexpected`（A/C IDs+ titles）
  - `collision_insight_ja`（A+C 碰撞解釋，內部新增）
  - `unexpected_score`、`impact_score`、`plausibility_score`（同步打分）
- **輸出**：`d_phase2_scenarios.json` + checkpoint
- **Cache 失效**：pairs signature 變動

### Phase 3：評分 + Gate + Matrix 分類

- **Model**：gpt-5
- **3 個維度**（`d_phase3_rank.txt`）：

| Dim | 來源 | 用途 |
|---|---|---|
| `unexpected_score` | 🟢 客戶原始 | 加權 |
| `impact_score` | 🟢 客戶原始 | 加權（business impact = revenue / competitive position）|
| `plausibility_score` | ➕ 我們加的（per JRI 4/2 反饋）| 加權（2026-04-27 起從 pass/fail gate 改為 weighted dim）|

- `weighted_score = Σ (D_WEIGHTS[dim] × dim_score)` for all 3 dims
- `total_score` 改成 3 維加總（max 30）
- `pick_final` 選 top `D_GENERATE_N`
- 若 `D_MATRIX_MODE = True`：用最終 N 個的 median 切 2×2 → `breakthrough` / `surprising` / `incremental` / `low_priority`
- C 再導出：只保留被 D 引用到的 C scenarios → `C_used_in_D_{ja,zh}.json`

---

## 七、Cache 與成本一覽

| 階段 | LLM call 數 | Cache 穩? | 觸發重跑的條件 |
|---|---|---|---|
| A1 Phase 1（摘要）| ~720 articles | ✅ 穩 | input 檔 / prompt |
| A1 Phase 2（cluster + LLM 命名）| ~30-90 群 | ❌ 每次重跑（便宜）| 每次 |
| A1 Phase 3（生成）| pool_n（最多 90）| ✅ 穩 | themes 變 |
| A1 Phase 4（rank + pick）| 每 30 個 1 batch + 1 次 pick | ❌ 每次重跑 | 每次 |
| B Phase 1（評分）| 8000+ signals → ~360 batches | ✅ 穩（最重要的 cache）| input / prompt / topic / model |
| B Phase 2（去重）| ~3000 / 600/batch | ❌ 每次重跑（中等）| 每次 |
| C Phase 1（cluster + 命名）| ~20-60 群 | ❌ 每次重跑 | 每次（cluster_pair 模式還有隨機性）|
| C Phase 2（生成）| pool_n（~20-200）| ✅ 穩 | clusters 變 |
| C Phase 3（rank + pick）| ~1 batch | ❌ | 每次 |
| D Phase 1（配對）| 1 LLM call (select_pairs) | ✅ 穩（freshness check）| A/C output mtime |
| D Phase 2（生成）| pool_n（最多 60）| ✅ 穩 | pairs 變 |
| D Phase 3（rank + gate + pick）| 1 batch | ❌ | 每次 |

**改設定影響範圍速查**

| 改什麼 | 觸發誰重跑 |
|---|---|
| Articles.xlsx | A1 全 4 phase |
| Signals.xlsx | B Phase 1 全跑（最貴） |
| A1 weights / N | A1 Phase 2-4 重跑（Phase 1 cache 命中）|
| B weights / B_TOP_N | 只 B Phase 2 重跑（便宜）|
| C weights / N / mode | C 全 phase |
| D weights / gate / mode | D Phase 1-3 重跑 |
| topic / industries / known_domains | A1 Phase 3-4 + B Phase 1 + C/D |
| 跑 A1 重生成 | C 不會（B 已隔離）；D 會（A1 output 變了）|

---

## 八、模型分工

| 任務 | Model | 為什麼 |
|---|---|---|
| 摘要 / 輕量分類 | claude-haiku-4-5 | 便宜、快 |
| 主題命名 / 情境生成 | claude-opus-4-6 | 品質要求高 |
| 評分 / 排序 / pick_final | gpt-5 | JSON 結構化輸出穩定 |
| ja→zh 翻譯 | gpt-5（cfg.TRANSLATE_MODEL）| 雙語對照 |
| Embedding | text-embedding-3-small | clustering 用 |

---

## 九、客戶原始 vs 我們新增（dimension 層級）

按 `clients need/final_criteria_v2.md` 為準。

| Step | Dim | 來源 |
|---|---|---|
| **A1** | structural_depth、irreversibility、industry_related、feasibility | 🟢 客戶原始 |
| A1 | topic_relevance | ➕ 我們加（2026-04-27 從 `relevance` 拆出獨立計分）|
| **B** | outside_area、novelty、social_impact | 🟢 客戶原始 |
| **C** | unexpectedness、social_impact、uncertainty | 🟢 客戶原始 |
| **D** | unexpected_score、impact_score | 🟢 客戶原始 |
| D | plausibility_score（weighted dim）| ➕ 我們加（per JRI 4/2 反饋同意；2026-04-27 從 gate 改為 weighted）|
| D | matrix quadrant 分類 | ➕ 我們加（per JRI 4/2 反饋同意）|

**原則**：客戶原始維度的名稱與定義不可改；要新增另立維度，不混合進舊的。

---

## 十、整體流程摘要

1. 用戶在 UI（http://localhost:8080）設定 N、weights、mode
2. 按 Run All（或單步）→ 系統 over-generate → 加權排序 → pick_final 選 top N
3. 結果寫入 `data/output/{topic}/`：4 個 main JSON + xlsx + 1 個 C_used_in_D 子集
4. 可在 Results tab 直接生成 Japanese PPTX（`generate_pptx.js`）

**驗證**：`python validate_output.py` 檢查 score 欄位 + dimension 門檻 + 引用一致性。
