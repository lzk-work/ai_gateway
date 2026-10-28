from __future__ import annotations

from typing import Any


RISK_LEVELS = {"PASS", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
RISK_ANSWERS = {"是", "否", "Verification Required"}
PATENT_STATUSES = {
    "Active",
    "Granted",
    "Application",
    "Expired",
    "Abandoned",
    "Cancelled",
    "Lapsed",
    "Unknown",
    "Status Verification Required",
}


def validate(source: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    source_sku = str(source.get("SKU") or "").strip()
    if str(parsed.get("SKU") or "").strip() != source_sku:
        raise ValueError("返回SKU与输入SKU不一致")
    for field in ("专利风险等级", "版权风险等级", "总体风险等级"):
        if parsed[field] not in RISK_LEVELS:
            raise ValueError(f"{field}不符合固定枚举: {parsed[field]}")
    for field in ("专利风险", "版权风险"):
        if parsed[field] not in RISK_ANSWERS:
            raise ValueError(f"{field}不符合固定枚举: {parsed[field]}")
    if parsed["专利法律状态"] not in PATENT_STATUSES:
        raise ValueError(f"专利法律状态不符合固定枚举: {parsed['专利法律状态']}")
    return parsed
