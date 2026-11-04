from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = (
    ROOT
    / "subtasks"
    / "text_to_text"
    / "tasks"
    / "walmart_copy_optimization"
    / "validator.py"
)


def load_validator():
    spec = importlib.util.spec_from_file_location("walmart_copy_validator", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.validate


def success_payload():
    paragraph = " ".join(["Useful product information supports practical everyday use"] * 9)
    return {
        "status": "success",
        "product_description": [paragraph, paragraph, paragraph],
        "feature_1": "Supported function for practical daily use.",
        "feature_2": "Clear construction details support informed selection.",
        "feature_3": "The supplied design details explain ordinary operation.",
        "feature_4": "Included facts describe straightforward care and handling.",
        "feature_5": "Suitable for the usage setting stated in the source information.",
    }


def test_success_response_is_validated_and_flattened_for_excel():
    result = load_validator()({}, success_payload())
    assert result["status"] == "success"
    assert result["product_description"].count("\n\n") == 2
    assert result["feature_5"].startswith("Suitable")


def test_fail_response_is_a_valid_business_result():
    assert load_validator()({}, {"status": "fail", "message": "Source details are insufficient."}) == {
        "status": "fail",
        "message": "Source details are insufficient.",
    }


def test_success_response_requires_exact_field_order():
    payload = success_payload()
    payload["extra"] = "not allowed"
    with pytest.raises(ValueError, match="字段名称或顺序"):
        load_validator()({}, payload)


def test_description_word_count_is_enforced():
    payload = success_payload()
    payload["product_description"] = ["Too short.", "Still short.", "Not enough words."]
    with pytest.raises(ValueError, match="英文词数"):
        load_validator()({}, payload)
