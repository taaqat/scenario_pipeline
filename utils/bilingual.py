"""
Bilingual output splitter + zh translation utilities.
Takes a JSON with _ja/_zh suffixed fields → produces two clean JSON files.
"""
import json
import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)


def strip_zh(obj):
    """Recursively remove all *_zh keys from dicts (keeps prompts lean)."""
    if isinstance(obj, dict):
        return {k: strip_zh(v) for k, v in obj.items() if not k.endswith("_zh")}
    elif isinstance(obj, list):
        return [strip_zh(i) for i in obj]
    return obj


_TRANSLATE_PROMPT = """\
You are a Japanese→Traditional Chinese (台灣繁體中文) translator for business strategy reports.
For each item in the JSON array below, translate all *_ja fields to *_zh.
Respond with a JSON object: {{"translations": [...]}} where the array has the SAME LENGTH as input.
Each element should contain ONLY the *_zh translations — do NOT repeat the _ja fields.

# 核心原則（依優先序）

1. **意譯，不是字譯。** 你的任務是用台灣商業人士日常使用的繁體中文「重寫」這段內容。讀者應覺得這本來就是中文寫的，而非翻譯稿。
2. **日文漢字 ≠ 中文。** 日文裡的漢字詞彙經常在中文裡不存在、語感不同、或有完全不同的對應詞。遇到日文特有詞彙（如介護、自治体、定年、賦課制、縦割り等），必須轉換成台灣讀者熟悉的說法，不可直接沿用日文漢字。
3. **日文「〜化」造詞不可直譯。** 日文習慣用「X化」創造複合詞，但中文不一定有對應的「X化」。應拆解成動詞短語或自然的中文表達。
4. **字形要正確。** 日文漢字的字形可能與繁體中文不同（如齢→齡、経→經）。一律使用台灣繁體中文的正確字形。

# 句式規則
- 一句不超過40字。長句拆分。
- 禁止被動語態堆疊。日文的被動/推測表達一律轉為主動語態。
- 「的」不可連續出現超過2次。

# 保留規則
- 方括號標籤（[Opportunity], [Challenge], [自動車] 等）、場景編號（A-1, C-3, D-5）、(row_num)(year) 格式保持原樣。
- 專有名詞（公司名、產品名）保留原文並加中文簡短說明。一般概念直接翻成中文。
- 日文「・」改為中文「、」或「／」。

{items_json}"""


def translate_to_zh(
    items: list[dict],
    llm,
    model: str,
    batch_size: int = 1,
) -> list[dict]:
    """
    Add *_zh translations for all *_ja fields using LLM (Sonnet).
    Processes items in batches via concurrent_batch_call.
    Falls back to originals (without _zh) if translation fails.
    """
    from utils.data_io import chunk_list

    if not items:
        return items

    batches = chunk_list(items, batch_size)

    def make_prompt(batch):
        compact = [
            {k: v for k, v in item.items() if k.endswith("_ja")}
            for item in batch
        ]
        return _TRANSLATE_PROMPT.format(
            items_json=json.dumps(compact, ensure_ascii=False, indent=1)
        )

    results = llm.concurrent_batch_call(
        items=batches,
        prompt_fn=make_prompt,
        model=model,
        desc="Translate ja→zh",
        max_workers=min(len(batches), 10),
        max_tokens=16000,
    )

    # Use indexed dict to preserve original order
    merged_by_global_idx: dict[int, dict] = {}
    failed_items: list[tuple[int, dict]] = []  # (global_idx, original_item)

    global_idx = 0
    for batch, result in zip(batches, results):
        # OpenAI json_object mode wraps arrays in a dict — unwrap it
        if isinstance(result, dict):
            result = next((v for v in result.values() if isinstance(v, list)), None)
        if result and isinstance(result, list) and len(result) == len(batch):
            for orig, trans in zip(batch, result):
                merged = dict(orig)
                if isinstance(trans, dict):
                    merged.update({k: v for k, v in trans.items() if k.endswith("_zh")})
                merged_by_global_idx[global_idx] = merged
                global_idx += 1
        else:
            logger.warning(f"Translation batch failed (got {len(result) if result else 0}, expected {len(batch)}) — will retry")
            for orig in batch:
                failed_items.append((global_idx, orig))
                global_idx += 1

    total_items = global_idx

    # ── Retry failed items (up to 2 rounds, one item at a time) ──
    max_retries = 2
    for retry_round in range(1, max_retries + 1):
        if not failed_items:
            break
        logger.info(f"Translation retry round {retry_round}: {len(failed_items)} items, single-item calls")

        retry_batches = [[item] for _, item in failed_items]
        retry_indices = [idx for idx, _ in failed_items]

        retry_results = llm.concurrent_batch_call(
            items=retry_batches,
            prompt_fn=make_prompt,
            model=model,
            desc=f"Translate-retry-{retry_round}",
            max_workers=min(len(retry_batches), 10),
            max_tokens=16000,
        )

        still_failed = []
        for (gidx, orig), result in zip(failed_items, retry_results):
            if isinstance(result, dict):
                result = next((v for v in result.values() if isinstance(v, list)), None)
            if result and isinstance(result, list) and len(result) == 1:
                merged = dict(orig)
                if isinstance(result[0], dict):
                    merged.update({k: v for k, v in result[0].items() if k.endswith("_zh")})
                merged_by_global_idx[gidx] = merged
            else:
                still_failed.append((gidx, orig))

        if still_failed:
            logger.warning(f"Translation retry round {retry_round}: {len(still_failed)} items still failed")
            failed_items = still_failed
        else:
            logger.info(f"Translation retry round {retry_round}: all recovered")
            failed_items = []

    # Any remaining failures — keep originals without _zh at their original position
    if failed_items:
        logger.warning(f"Translation: {len(failed_items)} items still without _zh after {max_retries} retries")
        for gidx, orig in failed_items:
            merged_by_global_idx[gidx] = orig

    # Rebuild output in original order (fallback to original item if index missing)
    return [merged_by_global_idx.get(i, items[i] if i < len(items) else {}) for i in range(total_items)]


def split_bilingual(data: Union[dict, list], lang: str) -> Union[dict, list]:
    """
    Recursively strip language suffixes from field names.

    For lang="ja": keeps _ja fields, removes _zh fields, strips the _ja suffix.
    For lang="zh": keeps _zh fields, removes _ja fields, strips the _zh suffix.

    Fields without _ja/_zh suffix are kept as-is (shared fields like scenario_id).
    """
    _ALL_SUFFIXES = ("_ja", "_zh")
    keep_suffix = f"_{lang}"
    drop_suffixes = [s for s in _ALL_SUFFIXES if s != keep_suffix]

    if isinstance(data, list):
        return [split_bilingual(item, lang) for item in data]

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if any(key.endswith(ds) for ds in drop_suffixes):
                # Skip other languages
                continue
            elif key.endswith(keep_suffix):
                # Keep this field, strip suffix
                clean_key = key[:-len(keep_suffix)]
                result[clean_key] = split_bilingual(value, lang)
            else:
                # Shared field (no suffix) — keep as-is
                result[key] = split_bilingual(value, lang)
        return result

    # Primitive types — return as-is
    return data


def save_split(
    data: Union[dict, list],
    output_dir: Union[str, Path],
    base_name: str,
    indent: int = 2,
):
    """
    Save a bilingual JSON as two separate files:
      {base_name}_ja.json — Japanese version (clean field names)
      {base_name}_zh.json — Traditional Chinese version (clean field names)
    
    Args:
        data: The bilingual JSON data (with _ja/_zh suffixed fields)
        output_dir: Directory to save to
        base_name: Base filename without extension (e.g., "A1_expected_scenarios")
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for lang in ["ja", "zh"]:
        split_data = split_bilingual(data, lang)
        out_path = output_dir / f"{base_name}_{lang}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(split_data, f, ensure_ascii=False, indent=indent)
        logger.info(f"Saved: {out_path}")
    
    return {
        "ja": output_dir / f"{base_name}_ja.json",
        "zh": output_dir / f"{base_name}_zh.json",
    }
