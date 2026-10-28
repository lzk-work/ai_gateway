from __future__ import annotations

import re
from typing import Any


def _find(row: dict[str, Any], name: str) -> str:
    wanted = name.casefold()
    for key, value in row.items():
        if str(key).strip().casefold() == wanted:
            return "" if value is None else str(value).strip()
    return ""


def validate(row: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    sku = _find(row, "sku")
    title = _find(row, "title_1688")
    if str(parsed.get("SKU", "")).strip() != sku:
        raise ValueError("返回 SKU 与输入不一致")
    if str(parsed.get("1688原始标题", "")).strip() != title:
        raise ValueError("返回1688原始标题与输入不一致")
    keywords: list[str] = []
    for item in re.split(r"[;；\n]+", str(parsed.get("提取关键词", ""))):
        value = item.strip(" ,，、")
        if value and value not in keywords:
            keywords.append(value)
    if not keywords:
        raise ValueError("提取关键词为空")
    parsed["提取关键词"] = "; ".join(keywords)
    return parsed
