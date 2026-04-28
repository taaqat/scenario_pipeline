# Handoff — JRI Scenario Pipeline

For the engineer taking over deployment. Read this first; setup details are in `README.md`.

---

## What this is

Web tool for **JRI (日本綜合研究所)**: takes news articles + weak signals → generates 4 types of scenarios (A1 Expected, B Selected Signals, C Unexpected, D Opportunities) → produces a Japanese PowerPoint deck.

Stack: Python 3.13 + NiceGUI + Claude API + OpenAI API + Node.js (PPTX) + BERTopic (clustering).

Customer deliverable spec lives in `clients need/` — **read those before touching prompts or output structure**:
- `final_criteria_v2.md` — JRI's authoritative dimension definitions
- `20250509 LivingLab+JRI.pptx` — visual output references (slides 16-19)
- `(signed QUOTATION)*.pdf` — contract scope

---

## Current state (2026-04-28)

- ✅ All 4 steps run end-to-end (`python app.py` → http://localhost:8080, login `jri/livinglab2026`)
- ✅ All criterion definitions match `final_criteria_v2.md` verbatim in prompts + UI hints
- ✅ Cost report resets per-run (not cumulative across runs)
- ✅ B Phase 1 cache (~$25 per rebuild) is decoupled from A1 — only Excel/prompt/topic invalidates it
- ⚠️ Running only on dev's Mac. Not deployed anywhere yet.

---

## API keys

Two required, get from project owner via secure channel (1Password / Bitwarden — **never commit**):

```bash
cp .env.example .env
# Fill in:
#   ANTHROPIC_API_KEY=sk-ant-...    (Claude — A1/C/D generation, cluster naming)
#   OPENAI_API_KEY=sk-proj-...       (OpenAI — B scoring, all ranking, embeddings)
```

Cost per full run (A1+B+C+D):
- First time: ~$40 USD (B Phase 1 scores 9000 signals, ~$25 alone)
- Subsequent runs: ~$15 USD (B Phase 1 hits cache; only generation + ranking re-runs)

`data/output/{topic}/cost_report.json` shows the **current run only** (resets each Run).

---

## Deploy options

Pick one based on customer access pattern:

| Option | When | Effort |
|---|---|---|
| **Cloudflare Tunnel** (`cloudflared tunnel --url http://localhost:8080`) | Short demo, dev's Mac stays on | 5 min |
| **Render.com / Railway / Fly.io** (push Dockerfile) | Customer wants persistent URL, we host | ~1 day |
| **Customer-internal deploy** (give them this repo + setup) | Customer's IT runs it, uses their own API keys | half day to write deploy guide |

Recommend **customer-internal** long-term — costs go to JRI's API account, no liability for us.

---

## Must-fix BEFORE giving to customer

🔴 these are sharp edges left from dev mode:

1. **Hardcoded login** in `app.py` (search `"jri"` and `"livinglab2026"`) → read from env vars `WEB_USERNAME` / `WEB_PASSWORD`
2. **NiceGUI session secret** is hardcoded `"livinglab+jri"` → random 32-char string from `NICEGUI_SECRET` env var
3. **Input Excel paths hardcoded** in `configs/jri_aging.py`. Customer can't upload via UI — they need a file or we add an upload form
4. **Log path** `pipeline.log` writes to project root → fails on read-only filesystems (Render free tier). Move to `/tmp/pipeline.log`

🟠 nice-to-have:
- Rate-limit the Run button (avoid customer mashing it and burning API credits)
- Add cost alert (email if run cost > threshold)

---

## Critical design decisions (don't undo without thinking)

- **BERTopic for A1/C clustering** (not k-means): small specialty topics like 金融/食/住居 surface as own clusters instead of being absorbed into the dominant aging-care cluster. See `pipeline_flow_document.md` §三.
- **B Phase 1 doesn't read A1**: signature deliberately excludes A1 output, so A1 changes don't trigger expensive 9000-signal re-scoring. Customer's spec mentions "outside the perspective of client employees" not "outside Expected Scenarios" — so this aligns with spec.
- **D Plausibility is a weight, not a gate** (since 2026-04-27): equal treatment with the other dims, no pass/fail filtering.
- **Cost tracker resets per run**: each run's cost report is standalone. `app.py` `run_step()` calls `tracker.reset()` + `oai.reset_usage()` at start.

---

## Known unfinished items

| Item | Severity | Notes |
|---|---|---|
| **D Implications structure mismatch** | 🟡 visible to customer | Customer's slide 19 shows a 3×3 table (時間軸 × 面向 — From now on / Establishment / Growth × Social Needs / Application / Company's Role). We output flat `[Opportunity]/[Challenge] × industries`. Customer may ask. |
| **Idea E (image / video visualization)** | 🟡 in contract | Not implemented. Customer's quotation appendix lists "10 Concept Images or Videos (~10s each)" |
| **UI is English-only** | 🟡 customer is Japanese | Step descriptions, labels, hints all English. Customer may need translator. |
| **Cost shown in USD** | ⚪ minor | Japanese customer might want JPY |
| **No bulk Excel upload** | 🟠 deploy blocker | Inputs hardcoded in `configs/*.py` |

---

## Code map

```
app.py                  — NiceGUI Web UI (~1200 lines, all-in-one)
config.py               — global settings + UI_PARAMS + apply_overrides()
configs/                — per-topic configs (jri_aging.py, energy.py)
prompts/                — 13 LLM prompt templates
steps/                  — A1 / B / C / D pipeline logic
utils/
  ├── llm_client.py     — Claude wrapper (CostTracker)
  ├── openai_client.py  — OpenAI wrapper
  ├── data_io.py        — rank_and_select, pick_final, apply_scores
  ├── clustering.py     — BERTopic + build_cluster_dicts
  └── bilingual.py      — ja↔zh save/translate helpers
generate_pptx.js        — PowerPoint deck builder (Node.js)
run_pipeline.py         — CLI entry + save_cost_report()
validate_output.py      — output sanity checker
test_checkpoint.py      — B cache logic test (sandboxed, won't trash prod cache)
run_smoke.py            — end-to-end smoke run with small N
clients need/           — JRI's authoritative spec docs (read these!)
```

---

## First-day checklist

- [ ] Clone, `pip install -r requirements.txt`, `npm install`, set `.env`, run `python app.py` — login + see 4 tabs
- [ ] Run `python run_smoke.py` — small-N end-to-end run completes
- [ ] Read `clients need/final_criteria_v2.md` (10 min)
- [ ] Skim `pipeline_flow_document.md` (15 min)
- [ ] Look at `0509 LivingLab+JRI.pptx` slides 16-19 (the customer's reference outputs)
- [ ] Pick deploy option, list any blockers, sync with project owner

---

## Contacts

- Project owner: [your name + email]
- JRI contact: [their name]
- API key holder: [admin name]
