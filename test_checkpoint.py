import io
import json
import logging
import sys
import os

# SAFETY: only run as `python test_checkpoint.py`. Refuse to execute when
# imported (e.g. by static-analysis sweeps) — this script writes b_phase1_scored.json
# with a fake LLM client and would otherwise overwrite the production cache.
if __name__ != "__main__":
    raise RuntimeError(
        "test_checkpoint.py is a destructive smoke test — run it directly, "
        "do not import it. It writes dummy data to b_phase1_scored.json."
    )

try:
    import config as cfg
    from config import apply_overrides
    from steps import step_b
except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)

# Redirect intermediate output to an isolated test directory so the production
# B Phase 1 cache (8000+ real LLM-scored signals) is never overwritten.
_TEST_INTERMEDIATE = cfg.BASE_DIR / "data" / "intermediate" / "_test_checkpoint"
_TEST_INTERMEDIATE.mkdir(parents=True, exist_ok=True)
cfg.INTERMEDIATE_DIR = _TEST_INTERMEDIATE
print(f"[test_checkpoint] sandbox INTERMEDIATE_DIR = {_TEST_INTERMEDIATE}")

orig_topic = cfg.TOPIC
orig_smoke = cfg.SMOKE_TEST
orig_rows = cfg.SMOKE_ROWS
orig_topn = cfg.B_TOP_N
orig_client_factory = getattr(step_b, 'get_openai_client', None)

class FakeClient:
    def set_step(self, step):
        self.step = step

    def concurrent_batch_call(
        self,
        items,
        prompt_fn,
        model,
        desc,
        max_workers=1,
        on_item_done=None,
        temperature=None,
        max_tokens=None,
        use_tool=False,
    ):
        out = []
        for i, item in enumerate(items):
            _ = prompt_fn(item)
            if desc == "B-Score":
                _, batch_df = item
                recs = step_b.df_to_records(batch_df)
                result = {
                    "data": {
                        "signals": [
                            {
                                "signal_id": str(r.get("JRI ID") or r.get("signal_id") or f"S-{idx}"),
                                "title_ja": str(r.get("title_ja") or r.get("title") or "dummy"),
                                "scores": {
                                    "outside_area": 7,
                                    "novelty": 6,
                                    "social_impact": 8,
                                },
                                "total_score": 21,
                                "reasoning_ja": "stub",
                            }
                            for idx, r in enumerate(recs, 1)
                        ]
                    }
                }
            else:
                result = {"clusters": []}

            if on_item_done:
                on_item_done(i, result)
            out.append(result)
        return out

def run_case(tag, topic):
    apply_overrides({"TOPIC": topic, "B_TOP_N": 30})
    stream = io.StringIO()
    h = logging.StreamHandler(stream)
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter("%(name)s %(message)s"))
    root = logging.getLogger()
    for existing_h in root.handlers[:]:
        root.removeHandler(existing_h)
    root.addHandler(h)
    error = None
    try:
        step_b.score_signals()
    except Exception as e:
        error = str(e)
    finally:
        root.removeHandler(h)

    txt = stream.getvalue()
    flags = {
        "stale": "checkpoint is stale (prompt/context changed)" in txt,
        "assemble": "All B-score batches complete — assembling from checkpoint" in txt,
        "scoring": ("Scoring " in txt and "remaining batches" in txt),
        "error": error,
    }

    print(f"CASE {tag}")
    print(json.dumps(flags, ensure_ascii=False))
    for line in txt.splitlines():
        if (
            "B-score checkpoint" in line
            or "checkpoint is stale" in line
            or ("Scoring " in line and "remaining batches" in line)
            or "All B-score batches complete" in line
        ):
            print(line)
    print("---")
    return flags

step_b.get_openai_client = lambda: FakeClient()
cfg.SMOKE_TEST = True
cfg.SMOKE_ROWS = 10
logging.getLogger().setLevel(logging.INFO)

r1 = run_case("1_same_first", orig_topic)
r2 = run_case("2_same_second", orig_topic)
r3 = run_case("3_topic_changed", f"{orig_topic} [smoke-change]")

# restore
if orig_client_factory:
    step_b.get_openai_client = orig_client_factory
cfg.SMOKE_TEST = orig_smoke
cfg.SMOKE_ROWS = orig_rows
apply_overrides({"TOPIC": orig_topic, "B_TOP_N": int(orig_topn or 2000)})

print("SUMMARY")
print(json.dumps({"run1": r1, "run2": r2, "run3": r3}, ensure_ascii=False))
