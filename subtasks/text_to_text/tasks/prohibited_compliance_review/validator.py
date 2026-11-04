from __future__ import annotations

from typing import Any


FIELDS = [
    "SKU",
    "产品识别",
    "是否存在风险",
    "总体风险等级",
    "核心风险类别",
    "涵盖风险",
    "产品本身风险",
    "文案风险",
]
RISK_LEVELS = {"PASS", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
YES_NO = {"是", "否"}
PRODUCT_CONTENT_RISK = {"Yes", "No", "Verification Required"}


def validate(source: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    if list(parsed) != FIELDS:
        raise ValueError("JSON字段名称或顺序不符合固定8字段要求")
    if any(not isinstance(parsed[field], str) for field in FIELDS):
        raise ValueError("JSON全部字段值必须为字符串")

    source_sku = str(source.get("SKU") or "").strip()
    if parsed["SKU"].strip() != source_sku:
        raise ValueError("返回SKU与输入SKU不一致")
    if parsed["是否存在风险"] not in YES_NO:
        raise ValueError("是否存在风险只能为：是 / 否")
    if parsed["总体风险等级"] not in RISK_LEVELS:
        raise ValueError("总体风险等级不符合固定枚举")
    for field in ("产品本身风险", "文案风险"):
        if parsed[field] not in PRODUCT_CONTENT_RISK:
            raise ValueError(f"{field}不符合固定枚举")

    level = parsed["总体风险等级"]
    has_risk = parsed["是否存在风险"]
    core = parsed["核心风险类别"].strip()
    covered = parsed["涵盖风险"].strip()
    if level == "PASS":
        if has_risk != "否":
            raise ValueError("PASS时是否存在风险必须为否")
        if core != "N/A" or covered != "N/A":
            raise ValueError("PASS时核心风险类别和涵盖风险必须为N/A")
    else:
        if has_risk != "是":
            raise ValueError("非PASS等级时是否存在风险必须为是")
        if core in {"", "N/A", "Requires Further Verification"}:
            raise ValueError("非PASS等级必须提供已确认的核心风险类别")
        covered_items = [item.strip() for item in covered.split(";") if item.strip()]
        if core not in covered_items:
            raise ValueError("核心风险类别必须同时包含在涵盖风险中")
    return parsed
