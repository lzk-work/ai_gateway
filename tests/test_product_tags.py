from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "subtasks" / "text_to_text" / "tasks" / "product_tags" / "validator.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("product_tags_validator", VALIDATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate


def valid_payload():
    return {
        "Product SKU": "A001",
        "一级类目": "家居用品",
        "二级类目": "收纳整理",
        "三级类目": "电池收纳盒",
        "季节属性": "四季通用",
        "节日属性": "无明显节日属性",
        "适用人群": "成人/家庭用户",
        "使用场景": "室内/办公",
        "功能属性": "收纳整理",
        "生命周期": "成熟期",
        "TikTok潜力": "低",
        "节日爆款潜力": "低",
        "Walmart同款": "是",
        "Amazon同款": "是",
        "Walmart竞争度": "高",
        "Amazon竞争度": "高",
        "Ozon竞争度": "中",
        "市场饱和度": "高",
        "广告价值等级": "B",
        "爆款指数": 55,
        "推荐运营方式": "铺货款",
    }


def test_product_tags_validator_accepts_exact_json_contract():
    payload = valid_payload()
    assert load_validator()({"SKU": "A001"}, payload) == payload


def test_product_tags_validator_requires_matching_sku():
    with pytest.raises(ValueError, match="输入SKU"):
        load_validator()({"SKU": "OTHER"}, valid_payload())


def test_product_tags_validator_rejects_extra_or_reordered_fields():
    payload = valid_payload()
    payload["extra"] = "x"
    with pytest.raises(ValueError, match="固定21字段"):
        load_validator()({"SKU": "A001"}, payload)


@pytest.mark.parametrize("score", [-1, 101, 50.5, "50", True])
def test_product_tags_validator_rejects_invalid_score(score):
    payload = valid_payload()
    payload["爆款指数"] = score
    with pytest.raises(ValueError, match="0到100"):
        load_validator()({"SKU": "A001"}, payload)


def test_product_tags_validator_rejects_unknown_enum():
    payload = valid_payload()
    payload["季节属性"] = "全年"
    with pytest.raises(ValueError, match="固定枚举"):
        load_validator()({"SKU": "A001"}, payload)
