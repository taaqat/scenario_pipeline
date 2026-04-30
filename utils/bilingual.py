"""
Bilingual output splitter — takes a JSON with _ja/_zh suffixed fields and
produces two clean JSON files (one per language).
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
