"""
Claude API client with batching, rate limiting, retry, and cost tracking.
"""
from __future__ import annotations

import re
import time
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from dataclasses import dataclass, field
from anthropic import Anthropic

from config import (
    ANTHROPIC_API_KEY, MODEL_PRIMARY, MODEL_LIGHT,
    MAX_TOKENS, RPM_LIMIT, RETRY_MAX, RETRY_DELAY
)

logger = logging.getLogger(__name__)


# ── Pricing (USD per 1M tokens, as of Feb 2026) ────
PRICING = {
    # model_string: (input_per_mtok, output_per_mtok)
    "claude-haiku-4-5-20251001":    (1.00,  5.00),
    "claude-sonnet-4-20250514":     (3.00, 15.00),
    "claude-sonnet-4-5-20250929":   (3.00, 15.00),
    "claude-sonnet-4-6":            (3.00, 15.00),
    "claude-opus-4-6":              (5.00, 25.00),
    "claude-opus-4-5-20250918":     (5.00, 25.00),
    # Aliases / fallback
    "claude-haiku":   (1.00,  5.00),
    "claude-sonnet":  (3.00, 15.00),
    "claude-opus":    (5.00, 25.00),
}

def _get_pricing(model: str) -> tuple[float, float]:
    """Get (input_cost, output_cost) per 1M tokens for a model."""
    if model in PRICING:
        return PRICING[model]
    # Try partial match
    for key, val in PRICING.items():
        if key in model or model in key:
            return val
    # Default to Sonnet pricing
    logger.warning(f"Unknown model '{model}' — defaulting to Sonnet pricing")
    return (3.00, 15.00)


@dataclass
class UsageRecord:
    """Single API call usage."""
    step: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class CostTracker:
    """Tracks cumulative token usage and costs across the pipeline."""
    records: list[UsageRecord] = field(default_factory=list)

    def add(self, step: str, model: str, input_tokens: int, output_tokens: int):
        in_price, out_price = _get_pricing(model)
        cost = (input_tokens * in_price + output_tokens * out_price) / 1_000_000
        rec = UsageRecord(
            step=step, model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
        self.records.append(rec)
        return rec

    def reset(self):
        """Clear all records so subsequent reports reflect only what runs after this point."""
        self.records = []

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def total_calls(self) -> int:
        return len(self.records)

    def summary_by_step(self) -> dict:
        """Aggregate usage per pipeline step."""
        steps = {}
        for r in self.records:
            if r.step not in steps:
                steps[r.step] = {
                    "calls": 0, "input_tokens": 0,
                    "output_tokens": 0, "cost_usd": 0.0,
                    "model": r.model,
                }
            s = steps[r.step]
            s["calls"] += 1
            s["input_tokens"] += r.input_tokens
            s["output_tokens"] += r.output_tokens
            s["cost_usd"] += r.cost_usd
        return steps

    def to_report(self) -> dict:
        """Generate a full cost report dict."""
        by_step = self.summary_by_step()
        return {
            "total": {
                "calls": self.total_calls,
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
                "total_tokens": self.total_input_tokens + self.total_output_tokens,
                "cost_usd": round(self.total_cost, 4),
            },
            "by_step": {
                step: {**v, "cost_usd": round(v["cost_usd"], 4)}
                for step, v in by_step.items()
            },
            "pricing_reference": {
                model: {"input_per_mtok": p[0], "output_per_mtok": p[1]}
                for model, p in PRICING.items()
                if len(model.split("-")) > 2  # skip short aliases like "claude-haiku"
            },
        }

    def print_summary(self):
        """Print a human-readable cost summary."""
        report = self.to_report()
        t = report["total"]
        print("\n" + "=" * 60)
        print("COST REPORT")
        print("=" * 60)
        print(f"Total API calls:    {t['calls']}")
        print(f"Total input tokens: {t['input_tokens']:,}")
        print(f"Total output tokens:{t['output_tokens']:,}")
        print(f"Total tokens:       {t['total_tokens']:,}")
        print(f"Total cost:         ${t['cost_usd']:.4f}")
        print("-" * 60)
        for step, v in report["by_step"].items():
            print(
                f"  {step:20s} | {v['calls']:3d} calls | "
                f"{v['input_tokens']:>9,} in | {v['output_tokens']:>9,} out | "
                f"${v['cost_usd']:.4f} | {v['model']}"
            )
        print("=" * 60)


def _bracket_stack(text: str) -> list[str]:
    """Return a stack of unclosed opening delimiters ('{' or '[') in text."""
    stack = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ('{', '['):
            stack.append(ch)
        elif ch == '}' and stack and stack[-1] == '{':
            stack.pop()
        elif ch == ']' and stack and stack[-1] == '[':
            stack.pop()
    return stack


def _repair_json(text: str) -> str:
    """
    Attempt to repair common JSON issues from LLM output:
    1. Remove trailing commas before ] or }
    2. Fix truncated JSON by closing unclosed brackets/braces
    3. Remove control characters inside strings
    4. Handle BOM and other invisible prefixes
    """
    # Remove BOM and zero-width characters
    text = text.lstrip("\ufeff\u200b\u200c\u200d")

    # Remove trailing commas before } or ] (with optional whitespace)
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Remove control characters (except \n, \r, \t which are valid in JSON strings)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

    stack = _bracket_stack(text)

    # Close unclosed structures (truncated output)
    if stack:
        # Find the last complete JSON item boundary: }, followed by more content
        last_comma = text.rfind('},')
        if last_comma > 0:
            remainder = text[last_comma + 2:]
            if remainder.count('{') > remainder.count('}') or remainder.count('[') > remainder.count(']'):
                text = text[:last_comma + 1]
                stack = _bracket_stack(text)

        # Close in reverse order (innermost first)
        closing = ['}' if opener == '{' else ']' for opener in reversed(stack)]
        text += ''.join(closing)

    return text


class LLMClient:
    """Wrapper around Claude API with rate limiting, retry, and cost tracking."""

    def __init__(self, api_key: str = None):
        self.client = Anthropic(api_key=api_key or ANTHROPIC_API_KEY)
        self.tracker = CostTracker()
        self._call_count = 0
        self._window_start = time.time()
        self._current_step = "unknown"  # Set by pipeline steps
        self._lock = threading.Lock()   # protects rate limiter + cost tracker

    def set_step(self, step_name: str):
        """Set current pipeline step name for cost tracking."""
        self._current_step = step_name

    # ── Rate limiter ────────────────────────────────
    def _wait_if_needed(self):
        """Thread-safe sliding-window rate limiter."""
        sleep_time = 0.0
        with self._lock:
            self._call_count += 1
            elapsed = time.time() - self._window_start
            if elapsed < 60 and self._call_count >= RPM_LIMIT:
                sleep_time = 60 - elapsed + 1
                self._call_count = 0
                self._window_start = time.time()
            elif elapsed >= 60:
                self._call_count = 1
                self._window_start = time.time()
        if sleep_time > 0:
            logger.info(f"Rate limit: sleeping {sleep_time:.0f}s")
            time.sleep(sleep_time)

    # ── Single call ─────────────────────────────────
    def call(
        self,
        prompt: str,
        system: str = "",
        model: str = None,
        max_tokens: int = None,
        temperature: float = 0.7,
    ) -> str:
        """Single LLM call with retry and token tracking."""
        model = model or MODEL_PRIMARY
        max_tokens = max_tokens or MAX_TOKENS

        for attempt in range(1, RETRY_MAX + 1):
            try:
                self._wait_if_needed()
                msg = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                # Track usage (thread-safe)
                usage = msg.usage
                with self._lock:
                    self.tracker.add(
                        step=self._current_step,
                        model=model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                    )
                return msg.content[0].text
            except Exception as e:
                logger.warning(f"Attempt {attempt}/{RETRY_MAX} failed: {e}")
                if attempt < RETRY_MAX:
                    time.sleep(RETRY_DELAY * attempt)
                else:
                    raise

    # ── JSON call ───────────────────────────────────
    def call_json(
        self,
        prompt: str,
        system: str = "",
        model: str = None,
        temperature: float = 0.5,
        max_tokens: int = None,
        _retries: int = 3,
    ) -> dict | list:
        """Call LLM and parse JSON from response, with repair + retry on parse failure."""
        for attempt in range(1, _retries + 1):
            extra_instruction = ""
            if attempt > 1:
                extra_instruction = "\n\n⚠ CRITICAL: Respond with ONLY valid JSON. No markdown fences, no explanation, no text before or after the JSON."
            raw = self.call(
                prompt + extra_instruction,
                system=system, model=model, temperature=temperature, max_tokens=max_tokens,
            )
            text = raw.strip()

            # Strip markdown code fences (```json ... ```)
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines[1:] if not l.strip().startswith("```")]
                text = "\n".join(lines)

            # Try to find JSON array/object if text has leading non-JSON content
            if text and not text.startswith(("[", "{")):
                for ch in ("[", "{"):
                    idx = text.find(ch)
                    if idx >= 0:
                        text = text[idx:]
                        break

            # Attempt 1: direct parse
            try:
                return json.loads(text)
            except json.JSONDecodeError as e1:
                # Attempt 2: handle "Extra data" (multiple JSON objects)
                if "Extra data" in str(e1):
                    try:
                        obj, _ = json.JSONDecoder().raw_decode(text)
                        return obj
                    except json.JSONDecodeError:
                        pass

                # Attempt 3: repair common issues and re-parse
                try:
                    repaired = _repair_json(text)
                    return json.loads(repaired)
                except json.JSONDecodeError as e2:
                    logger.warning(
                        f"JSON parse error (attempt {attempt}/{_retries}): {e1} → repair failed: {e2}"
                    )
                    logger.warning(f"Raw response (first 300 chars): {raw[:300]}")
                    if attempt >= _retries:
                        raise e1

    # ── JSON via tool_use (guaranteed valid JSON) ────
    _JSON_TOOL = {
        "name": "json_output",
        "description": "Output the result as structured JSON. Put the complete JSON result in the 'data' field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {
                    "description": "The complete JSON result (array or object)",
                }
            },
            "required": ["data"],
        },
    }

    def call_json_tool(
        self,
        prompt: str,
        system: str = "",
        model: str = None,
        temperature: float = 0.5,
        max_tokens: int = None,
    ) -> dict | list:
        """
        Call LLM using tool_use to guarantee valid JSON output.
        Claude is forced to call the json_output tool, so the result
        is always well-formed JSON — no markdown fences, no parse errors.
        """
        model = model or MODEL_PRIMARY
        max_tokens = max_tokens or MAX_TOKENS

        for attempt in range(1, RETRY_MAX + 1):
            try:
                self._wait_if_needed()
                msg = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system or "You are a JSON API. Always use the json_output tool to return results.",
                    messages=[{"role": "user", "content": prompt}],
                    tools=[self._JSON_TOOL],
                    tool_choice={"type": "tool", "name": "json_output"},
                )
                # Track usage
                usage = msg.usage
                with self._lock:
                    self.tracker.add(
                        step=self._current_step,
                        model=model,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                    )
                # Extract tool result
                for block in msg.content:
                    if block.type == "tool_use" and block.name == "json_output":
                        data = block.input.get("data", block.input)
                        return data
                # Fallback: if no tool_use block found, try text
                logger.warning("tool_use block not found in response — falling back to text parse")
                text = msg.content[0].text if msg.content else ""
                return json.loads(text)
            except Exception as e:
                logger.warning(f"call_json_tool attempt {attempt}/{RETRY_MAX} failed: {e}")
                if attempt < RETRY_MAX:
                    time.sleep(RETRY_DELAY * attempt)
                else:
                    raise

    # ── Concurrent batch call ────────────────────────
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
        use_tool: bool = False,
    ) -> list:
        """
        Process items in parallel using ThreadPoolExecutor.
        on_item_done(flat_idx, result) is called after each item finishes.
        Returns results list aligned to input order (None for failures).
        If use_tool=True, uses call_json_tool (tool_use) instead of call_json.
        """
        total = len(items)
        results = [None] * total
        temp_kwargs = {"temperature": temperature} if temperature is not None else {}
        json_fn = self.call_json_tool if use_tool else self.call_json

        def _process(args):
            flat_idx, item = args
            prompt = prompt_fn(item)
            logger.info(f"{desc}: {flat_idx+1}/{total}")
            try:
                result = json_fn(prompt, system=system, model=model, max_tokens=max_tokens, **temp_kwargs)
                return flat_idx, result
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error at item {flat_idx+1}: {e}")
                # call_json already has 3 internal retries with repair;
                # if we still get here, try one final time with explicit instruction
                retry_prompt = (
                    prompt
                    + "\n\n⚠ CRITICAL: You MUST respond with ONLY a valid JSON array or object. "
                    "No markdown code fences (```), no explanation text. Just raw JSON."
                )
                try:
                    result = json_fn(retry_prompt, system=system, model=model, max_tokens=max_tokens, **temp_kwargs)
                    return flat_idx, result
                except Exception:
                    logger.error(f"Skipping item {flat_idx+1} after all JSON retries failed")
                    return flat_idx, None
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


# ── Convenience ─────────────────────────────────────
_default_client: Optional[LLMClient] = None

def get_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
