from __future__ import annotations

from typing import Any


FIELDS = [
    "Product SKU",
    "一级类目",
    "二级类目",
    "三级类目",
    "季节属性",
    "节日属性",
    "适用人群",
    "使用场景",
    "功能属性",
    "生命周期",
    "TikTok潜力",
    "节日爆款潜力",
    "Walmart同款",
    "Amazon同款",
    "Walmart竞争度",
    "Amazon竞争度",
    "Ozon竞争度",
    "市场饱和度",
    "广告价值等级",
    "爆款指数",
    "推荐运营方式",
]

ENUMS = {
    "季节属性": {"春季", "夏季", "秋季", "冬季", "四季通用"},
    "节日属性": {
        "圣诞节", "万圣节", "情人节", "复活节", "独立日", "返校季",
        "感恩节", "母亲节", "父亲节", "无明显节日属性",
    },
    "功能属性": {
        "装饰类产品", "数码配件", "手机配件", "电脑配件", "家居用品",
        "厨房用品", "园艺用品", "汽车用品", "母婴用品", "宠物用品",
        "运动户外", "玩具产品", "服饰配件", "美妆工具", "收纳整理",
        "节日用品", "其他",
    },
    "生命周期": {"新品期", "成长期", "成熟期", "衰退期"},
    "TikTok潜力": {"低", "中", "高"},
    "节日爆款潜力": {"低", "中", "高"},
    "Walmart同款": {"是", "否"},
    "Amazon同款": {"是", "否"},
    "Walmart竞争度": {"低", "中", "高"},
    "Amazon竞争度": {"低", "中", "高"},
    "Ozon竞争度": {"低", "中", "高"},
    "市场饱和度": {"低", "中", "高"},
    "广告价值等级": {"A", "B", "C"},
    "推荐运营方式": {"铺货款", "利润款", "广告款", "TikTok测试款", "节日爆款"},
}

AUDIENCES = {"儿童", "成人", "老人", "男性", "女性", "宠物", "家庭用户", "通用"}
SCENES = {
    "室内", "户外", "旅行", "办公", "汽车", "宠物", "园艺", "运动健身",
    "厨房", "浴室", "卧室", "客厅", "商业使用", "节日装饰",
}


def _validate_combination(value: str, allowed: set[str], field: str) -> None:
    parts = [part.strip() for part in value.split("/") if part.strip()]
    if not parts or any(part not in allowed for part in parts):
        raise ValueError(f"{field}包含提示词未允许的值")


def validate(source: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    if list(parsed) != FIELDS:
        raise ValueError("JSON字段名称或顺序不符合固定21字段要求")

    for field in FIELDS:
        if field == "爆款指数":
            continue
        if not isinstance(parsed[field], str) or not parsed[field].strip():
            raise ValueError(f"{field}必须是非空字符串")
        parsed[field] = parsed[field].strip()

    source_sku = str(source.get("SKU") or "").strip()
    if parsed["Product SKU"] != source_sku:
        raise ValueError("返回Product SKU与输入SKU不一致")

    score = parsed["爆款指数"]
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError("爆款指数必须是0到100之间的整数")

    for field, allowed in ENUMS.items():
        if parsed[field] not in allowed:
            raise ValueError(f"{field}不符合提示词固定枚举")

    _validate_combination(parsed["适用人群"], AUDIENCES, "适用人群")
    _validate_combination(parsed["使用场景"], SCENES, "使用场景")
    return parsed
