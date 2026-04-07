"""
OpenAI API client — same interface as LLMClient (set_step, call_json, concurrent_batch_call).
Used by Step B.
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from config import OPENAI_API_KEY, MAX_TOKENS, RETRY_MAX, RETRY_DELAY

logger = logging.getLogger(__name__)

# ── Pricing (USD per 1M tokens) ────────────────────────
OPENAI_PRICING = {
    "gpt-4o":       (2.50, 10.00),
    "gpt-4o-mini":  (0.15,  0.60),
    "gpt-4.1":      (2.00,  8.00),
    "gpt-5":        (2.00,  8.00),   # used by TRANSLATE_MODEL
    "gpt-5.1":      (2.00,  8.00),
    "gpt-5.2":      (1.75, 14.00),   # official: $1.75 input / $14 output
    "gpt-5-mini":   (0.15,  0.60),   # update when official pricing is announced
}

# Models that only accept default temperature (1) — no custom temperature allowed
_TEMPERATURE_FIXED_MODELS = {"gpt-5", "gpt-5.2"}


class OpenAIClient:
    """
    Minimal OpenAI client matching the LLMClient interface used in step_b.py.
    Tracks cost per step identically to LLMClient.
    """

    def __init__(self):
        self._client = OpenAI(api_key=OPENAI_API_KEY)
        self._step = "openai"
        self._lock = threading.Lock()
        # Per-step cost tracking (same structure as LLMClient)
        self._usage: dict[str, dict] = {}

    def set_step(self, name: str):
        self._step = name
        if name not in self._usage:
            self._usage[name] = {"calls": 0, "input": 0, "output": 0, "model": ""}

    def _record(self, model: str, input_tok: int, output_tok: int):
        step = self._step
        with self._lock:
            if step not in self._usage:
                self._usage[step] = {"calls": 0, "input": 0, "output": 0, "model": ""}
            u = self._usage[step]
            u["calls"] += 1
            u["input"] += input_tok
            u["output"] += output_tok
            u["model"] = model

    def cost_report(self) -> dict:
        report = {}
        total_cost = 0.0
        for step, u in self._usage.items():
            model = u["model"]
            in_price, out_price = OPENAI_PRICING.get(model, (0, 0))
            cost = (u["input"] * in_price + u["output"] * out_price) / 1_000_000
            total_cost += cost
            report[step] = {
                "calls": u["calls"],
                "input_tokens": u["input"],
                "output_tokens": u["output"],
                "cost_usd": round(cost, 4),
                "model": model,
            }
        report["_total_cost_usd"] = round(total_cost, 4)
        return report

    def call(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = None,
        temperature: float = 0.5,
        system: str = "",
    ) -> str:
        model = model or "gpt-4o"
        max_tokens = max_tokens or MAX_TOKENS
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        for attempt in range(1, RETRY_MAX + 1):
            try:
                create_kwargs = dict(
                    model=model,
                    messages=messages,
                    max_completion_tokens=max_tokens,
                )
                if model not in _TEMPERATURE_FIXED_MODELS:
                    create_kwargs["temperature"] = temperature
                resp = self._client.chat.completions.create(**create_kwargs)
                usage = resp.usage
                self._record(model, usage.prompt_tokens, usage.completion_tokens)
                return resp.choices[0].message.content or ""
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{RETRY_MAX} failed: {e}")
                if attempt < RETRY_MAX:
                    time.sleep(RETRY_DELAY * attempt)
                else:
                    raise

    def call_json(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = None,
        temperature: float = 0.5,
        system: str = "",
    ):
        model = model or "gpt-4o"
        max_tokens = max_tokens or MAX_TOKENS
        sys_msg = system or "You are a JSON API. Always respond with valid JSON only."
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]

        for attempt in range(1, RETRY_MAX + 1):
            try:
                create_kwargs = dict(
                    model=model,
                    messages=messages,
                    max_completion_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                if model not in _TEMPERATURE_FIXED_MODELS:
                    create_kwargs["temperature"] = temperature
                resp = self._client.chat.completions.create(**create_kwargs)
                usage = resp.usage
                self._record(model, usage.prompt_tokens, usage.completion_tokens)
                text = resp.choices[0].message.content or ""
                try:
                    return json.loads(text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON parse error: {e}")
                    # Try repairing common JSON issues before re-calling API
                    try:
                        from utils.llm_client import _repair_json
                        repaired = _repair_json(text)
                        return json.loads(repaired)
                    except (json.JSONDecodeError, ImportError):
                        pass
                    # Retry with explicit reminder
                    if attempt < RETRY_MAX:
                        messages[-1]["content"] = (
                            prompt + "\n\n⚠ You MUST respond with valid JSON only."
                        )
                        time.sleep(RETRY_DELAY * attempt)
                        continue
                    raise
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{RETRY_MAX} failed: {e}")
                if attempt < RETRY_MAX:
                    time.sleep(RETRY_DELAY * attempt)
                else:
                    raise

    def concurrent_batch_call(
        self,
        items: list,
        prompt_fn,
        system: str = "",
        model: str = None,
        desc: str = "Processing",
        max_workers: int = 5,
        on_item_done=None,
        max_tokens: int = None,
        temperature: float = None,
    ) -> list:
        """
        Same interface as LLMClient.concurrent_batch_call.
        """
        total = len(items)
        results = [None] * total
        temp_kwargs = {"temperature": temperature} if temperature is not None else {}

        def _process(args):
            flat_idx, item = args
            prompt = prompt_fn(item)
            logger.info(f"{desc}: {flat_idx+1}/{total}")
            try:
                result = self.call_json(
                    prompt, system=system, model=model, max_tokens=max_tokens, **temp_kwargs
                )
                return flat_idx, result
            except Exception as e:
                logger.error(f"Error at item {flat_idx+1}: {e}")
                return flat_idx, None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_process, (i, item)): i
                for i, item in enumerate(items)
            }
            for future in as_completed(futures):
                try:
                    flat_idx, result = future.result()
                except Exception as e:
                    flat_idx = futures[future]
                    logger.error(f"Task {flat_idx+1} raised unhandled exception: {e}")
                    result = None
                results[flat_idx] = result
                if on_item_done:
                    on_item_done(flat_idx, result)

        return results


_openai_client: OpenAIClient | None = None


def get_openai_client() -> OpenAIClient:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAIClient()
    return _openai_client


# ── Embedding utilities ───────────────────────────────
import numpy as np

EMBED_MODEL = "text-embedding-3-large"


def get_embeddings(texts: list[str], model: str = EMBED_MODEL) -> np.ndarray:
    """
    Get embeddings for a list of texts via OpenAI API.
    Returns numpy array of shape (len(texts), dim).
    """
    client = get_openai_client()
    # OpenAI embeddings API: max 300k tokens per request; use smaller batches
    BATCH = 256
    all_vecs = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i + BATCH]
        resp = client._client.embeddings.create(model=model, input=batch)
        vecs = [item.embedding for item in resp.data]
        all_vecs.extend(vecs)
    return np.array(all_vecs, dtype=np.float32)
