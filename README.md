# JRI Living Lab+ AI Scenario Pipeline

III × JRI 未來情境分析自動化 Pipeline

詳細流程請看 [pipeline_flow_document.md](pipeline_flow_document.md)。這份 README 只保留實作層面需要知道的現況。

## Architecture

```
7240 articles ──→ [A-1] Summarize(Haiku) → K-Means Cluster + Label(Opus) → Generate(Opus) → Rank + Gate + Review(gpt-5.2) ──→ all passed Expected Scenarios ──┐
                                                                                                                                                                   ├──→ [D] Pair Select(Opus) → Generate(Opus) → Rank + Gate + Review(gpt-5.2) ──→ all passed Opportunity Scenarios
9000+ signals ──→ [B] Score(gpt-5.2) → Top 3000 → Diversity Dedup(gpt-5.2) ──→ 2000 selected signals ──→ [C] K-Means Cluster + Label(Opus) → Generate(Opus) → Rank + Gate + Review(gpt-5.2) ──→ all passed Unexpected Scenarios ──┘
```

補充：
- A1、C、D 不再有硬性的 deliver N 上限，會輸出所有通過門檻的情境。
- D 讀的是人工篩選後的 A1 / C 輸出，而不是原始全量候選；如有人工調整，後續步驟請直接以 JSON 輸出為準。
- 所有正式輸出目前只保留日文與繁中版本。

## Setup

```bash
pip install -r requirements.txt
```

在專案根目錄建立 `.env`，至少包含：

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

## Data Preparation

把輸入檔放進 `data/input/`，必要時可在 `config.py` 改檔名：
- `日本 JRI aging 7240 rows.xlsx` → `A1_INPUT_FILE`
- `Weak signals 2026-02-25_073946.xlsx` → `B_INPUT_FILE`

## Usage

```bash
# Run everything
python3 run_pipeline.py

# Run individual steps
python3 run_pipeline.py --step a1
python3 run_pipeline.py --step b
python3 run_pipeline.py --step c
python3 run_pipeline.py --step d

# Run A-1 phase by phase
python3 run_pipeline.py --step a1 --phase 1   # summarize articles
python3 run_pipeline.py --step a1 --phase 2   # cluster into themes
python3 run_pipeline.py --step a1 --phase 3   # generate scenarios
python3 run_pipeline.py --step a1 --phase 4   # rank, gate filter, global review

# Re-run ranking only on existing generated pools
python3 rerank.py A
python3 rerank.py C --limit 100
python3 rerank.py D --no-translate
```

## Models Used

| Step | Task | Model |
|------|------|-------|
| A1 Phase 1 | Article summarize | Claude Haiku 4.5 |
| A1 Phase 2 | K-Means cluster labeling | Claude Opus 4.6 |
| A1 Phase 3 | Scenario generation | Claude Opus 4.6 |
| A1 Phase 4 | Ranking + review | gpt-5.2 |
| B Phase 1 | Signal scoring | gpt-5.2 |
| B Phase 3 | Diversity dedup | gpt-5.2 |
| C Phase 1 | K-Means cluster labeling | Claude Opus 4.6 |
| C Phase 2 | Scenario generation | Claude Opus 4.6 |
| C Phase 3 | Ranking + review | gpt-5.2 |
| D Phase 1 | Pair selection | Claude Opus 4.6 |
| D Phase 2 | Opportunity generation | Claude Opus 4.6 |
| D Phase 3 | Ranking + review | gpt-5.2 |
| All steps | ja→zh translation | gpt-5 |

## Deliverables

| Item | Count | Files |
|------|-------|-------|
| Expected Scenarios | All gate-passing items | `A1_expected_scenarios_ja/zh.json`, `.xlsx` |
| Selected Weak Signals | 2000 | `B_selected_weak_signals_ja/zh.json`, `.xlsx` |
| Unexpected Scenarios | All gate-passing items | `C_unexpected_scenarios_ja/zh.json`, `.xlsx` |
| C scenarios referenced by D | Derived from final D output | `C_used_in_D_ja/zh.json`, `.xlsx` |
| Opportunity Scenarios | All gate-passing items | `D_opportunity_scenarios_ja/zh.json`, `.xlsx` |

## Project Structure

```
jri_pipeline/
├── config.py
├── run_pipeline.py
├── rerank.py
├── generate_pptx.js
├── package.json
├── requirements.txt
├── CLAUDE_CODE_GUIDE.md
├── README.md
├── pipeline_flow_document.md
├── prompts/
│   ├── a1_phase1_summarize.txt
│   ├── a1_phase2_label_themes.txt
│   ├── a1_phase3_generate.txt
│   ├── a1_phase4_rank.txt
│   ├── b_phase1_score_signals.txt
│   ├── b_phase3_diversity_check.txt
│   ├── c_phase1_label_clusters.txt
│   ├── c_phase2_generate.txt
│   ├── c_phase3_rank.txt
│   ├── d_phase1_select_pairs.txt
│   ├── d_phase2_generate.txt
│   ├── d_phase3_rank.txt
│   └── review_scenarios.txt
├── steps/
│   ├── step_a1.py
│   ├── step_b.py
│   ├── step_c.py
│   └── step_d.py
├── utils/
│   ├── llm_client.py
│   ├── openai_client.py
│   ├── bilingual.py
│   ├── clustering.py
│   └── data_io.py
└── data/
    ├── input/
    ├── intermediate/
    └── output/
```
