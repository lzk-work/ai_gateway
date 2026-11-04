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


def test_short_description_is_accepted_when_structure_is_valid():
    payload = success_payload()
    payload["product_description"] = [
        "Short first paragraph.",
        "Short second paragraph.",
        "Short third paragraph.",
    ]
    result = load_validator()({}, payload)
    assert result["status"] == "success"
    assert result["product_description"].count("\n\n") == 2


def test_description_over_300_words_is_rejected():
    payload = success_payload()
    long_paragraph = " ".join(["word"] * 101)
    payload["product_description"] = [long_paragraph, long_paragraph, long_paragraph]
    with pytest.raises(ValueError, match="不能超过300"):
        load_validator()({}, payload)
