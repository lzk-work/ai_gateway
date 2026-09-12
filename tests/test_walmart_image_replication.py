import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "subtasks/walmart_image_replication"
sys.path.insert(0, str(TASK))
sys.path.insert(0, str(ROOT / "src"))

from scripts.build_replication_input import build, preview
spec = importlib.util.spec_from_file_location("replication_workflow_common", TASK / "workflow_common.py")
replication = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(replication)
review_spec = importlib.util.spec_from_file_location(
    "replication_review", TASK / "05_export_replication_review.py"
)
review = importlib.util.module_from_spec(review_spec)
assert review_spec.loader is not None
review_spec.loader.exec_module(review)
from ai_gateway.subtasks.mxapi_generate_images import load_config, load_work_rows
from ai_gateway.subtasks.mxapi_generate_images import image_kind_enabled, sku_target_count, sku_targets_from_complete_rows


class ReplicationWorkflowTests(unittest.TestCase):
    def test_review_splits_every_one_thousand_skus(self):
        skus = [f"sku-{index}" for index in range(3500)]
        parts = review.split_skus(skus, 1000)
        self.assertEqual([len(part) for part in parts], [1000, 1000, 1000, 500])
        outputs = review.output_paths(Path("审核预览.xlsx"), len(parts))
        self.assertEqual(
            [path.name for path in outputs],
            ["审核预览_001.xlsx", "审核预览_002.xlsx", "审核预览_003.xlsx", "审核预览_004.xlsx"],
        )

    def test_main_and_sub_generation_switches_are_independent(self):
        data = replication.generation_config_data()
        cfg = load_config(replication.GENERATE_CONFIG, config_data=data)
        cfg.generate_main_images = False
        cfg.generate_sub_images = True
        self.assertFalse(image_kind_enabled(cfg, {"image_name": "new_main_sku1", "image_type": "Main Image"}))
        self.assertTrue(image_kind_enabled(cfg, {"image_name": "new_sub1_sku1", "image_type": "Replication 1"}))

    def test_workflow_keyboard_interrupt_between_cycles_is_clean(self):
        workflow_spec = importlib.util.spec_from_file_location(
            "replication_full_workflow", TASK / "00_replication_workflow.py"
        )
        workflow_module = importlib.util.module_from_spec(workflow_spec)
        assert workflow_spec.loader is not None
        workflow_spec.loader.exec_module(workflow_module)
        config = {
            "workflow": {},
            "scheduler": {
                "enabled": True,
                "interval_seconds": 600,
                "stop_when_complete": False,
                "max_cycles": None,
            },
        }
        with patch.object(workflow_module, "load_task_config", return_value=config), \
             patch.object(workflow_module, "run_step"), \
             patch.object(workflow_module.time, "sleep", side_effect=KeyboardInterrupt), \
             patch.object(sys, "argv", ["00_replication_workflow.py"]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            workflow_module.main()
        text = output.getvalue()
        self.assertIn("已在两轮之间安全停止", text)
        self.assertIn("图片复刻总流程结束", text)

    def test_business_prompts_are_local_to_replication_project(self):
        self.assertTrue((TASK / "prompts/main_image_optimization_prompt.txt").exists())
        source = (TASK / "01_build_replication_tasks.py").read_text(encoding="utf-8")
        self.assertNotIn('TASK_ROOT.parent / "walmart_image_prompt"', source)

    def test_builds_one_task_per_existing_sub_image_with_two_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.xlsx"
            output = root / "tasks.xlsx"
            template = root / "prompt.txt"
            template.write_text("T={{标题}} F={{五点}} D={{描述}}", encoding="utf-8")
            book = Workbook()
            sheet = book.active
            sheet.title = "Sheet1"
            headers = ["SKU", "标题", "五点", "描述", "主图", *[f"副图参考{i}" for i in range(1, 7)]]
            sheet.append(headers)
            sheet.append(["sku1", "title", "features", "description", "https://main", *[f"https://sub{i}" for i in range(1, 7)]])
            book.save(source)
            config = {
                "input": {
                    "excel_path": str(source), "sheet_name": "Sheet1",
                    "columns": {
                        "sku": "SKU", "title": "标题", "features": "五点", "description": "描述",
                        "main_image": "主图", "sub_images": [f"副图参考{i}" for i in range(1, 7)],
                    },
                }
            }
            preview_summary = preview(config)
            self.assertEqual(preview_summary["main_rows"], 1)
            self.assertEqual(preview_summary["sub_rows"], 5)
            self.assertEqual(
                [item["reference_count"] for item in preview_summary["samples"]],
                [1, 2, 2, 2, 2],
            )
            self.assertFalse(output.exists())
            main_template = root / "main_prompt.txt"
            main_template.write_text("MAIN", encoding="utf-8")
            summary = build(config, output, template, main_template)
            self.assertEqual(summary["generated_rows"], 6)
            self.assertEqual(summary["main_rows"], 1)
            self.assertEqual(summary["sub_rows"], 5)

            data = replication.generation_config_data()
            data["input"]["excel_path"] = str(output)
            data["output"] = {key: str(root / f"{key}.tmp") for key in (
                "excel_path", "results_path", "checkpoint_path", "download_dir", "raw_responses_dir"
            )}
            cfg = load_config(replication.GENERATE_CONFIG, config_data=data)
            rows, loaded_book, _, _ = load_work_rows(cfg)
            self.assertEqual(rows[0]["reference_image"], ["https://main"])
            self.assertEqual(rows[1]["reference_image"], ["https://main", "https://sub1"])
            self.assertEqual(rows[5]["reference_image"], ["https://main", "https://sub5"])
            self.assertEqual(rows[0]["prompt"], "MAIN")
            self.assertEqual(rows[1]["prompt"], "T=title F=features D=description")
            self.assertEqual(
                [row["image_name"] for row in rows],
                ["new_main_sku1", "new_sub1_sku1", "new_sub2_sku1", "new_sub3_sku1", "new_sub4_sku1", "new_sub5_sku1"],
            )
            cfg.prompt_mode = "fixed"
            cfg.desired_count = 7
            self.assertEqual(sku_target_count(cfg, rows), 6)
            targets = sku_targets_from_complete_rows(cfg, rows)
            self.assertEqual(targets["sku1"], 6)
            # Filtering four successful rows must not shrink the final target
            # to the two rows that remain pending.
            self.assertEqual(targets["sku1"], 4 + len(rows[4:]))
            loaded_book.close()


if __name__ == "__main__":
    unittest.main()
