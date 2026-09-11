"""Configuration integration tests; never call live APIs or write business batches."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "subtasks/walmart_image_prompt"
sys.path.insert(0, str(TASK))
sys.path.insert(0, str(ROOT / "src"))
import workflow_common as workflow
from ai_gateway.subtasks import mxapi_generate_images as images
from ai_gateway.subtasks import oss_upload_images as oss
from ai_gateway.subtasks import walmart_call_prompt_model as buzz
from ai_gateway.subtasks import walmart_get_pic_prompt as prompts


class ConfigurationTests(unittest.TestCase):
    def test_shared_gateway_retry_contract(self):
        from ai_gateway.config.loader import GatewayConfig
        from ai_gateway.retry_policy import gateway_max_attempts
        for provider in ("tuzi", "mxapi", "buzz"):
            for retries in (0, 2):
                gateway = GatewayConfig(provider, provider, "https://example.test", max_retries=retries)
                self.assertEqual(gateway_max_attempts(gateway), retries + 1)
            gateway.max_retries = -1
            with self.assertRaises(ValueError):
                gateway_max_attempts(gateway)

    def test_buzz_reads_gateway_retries(self):
        from ai_gateway.config.loader import GatewayConfig
        from ai_gateway.clients.openai_chat_client import OpenAIChatClient
        config = workflow.load_stage_config(workflow.CALL_MODEL_CONFIG, buzz.load_config)
        config.retry_delay_seconds = 0
        for retries in (0, 2):
            gateway = GatewayConfig("buzz", "buzz", "https://example.test", max_retries=retries)
            client = OpenAIChatClient(gateway)
            pool = buzz.RuntimeModelPool(gateway, config.model, [], enabled=False)
            with patch.object(buzz, "_call_model", side_effect=TimeoutError("timeout")) as call, \
                 contextlib.redirect_stdout(io.StringIO()):
                result = buzz.call_one(1, 1, {"task_id": "test", "next_task_payload": {"prompt": "test"}},
                                       config, client, "buzz", pool)
            self.assertEqual(call.call_count, retries + 1)
            self.assertEqual(result.status, "failed")

    def test_optional_temperature_is_omitted(self):
        payload = buzz.build_chat_payload(
            next_payload={"prompt": "test", "images": []},
            source_task={},
            prompt_override=None,
            model_name="gpt-5.6-luna",
            max_tokens=100,
            temperature=None,
            image_detail="auto",
        )
        self.assertNotIn("temperature", payload)
        responses_payload = buzz.build_responses_payload(payload)
        self.assertNotIn("temperature", responses_payload)

    def test_missing_source_image_is_a_terminal_precheck_failure(self):
        legacy_row = {
            "task_id": "batch:sku",
            "sku": "sku",
            "status": "failed",
            "retryable": False,
            "error_code": "PrecheckFailed",
            "error_message": '["missing image url"]',
        }
        self.assertTrue(buzz.is_completed_row(legacy_row))
        normalized = buzz.normalize_result_row(legacy_row)
        self.assertEqual(normalized["status"], "failed_permanent")
        self.assertEqual(normalized["error_code"], "ReferenceImageMissing")
        self.assertFalse(normalized["retryable"])

        config = workflow.load_stage_config(workflow.CALL_MODEL_CONFIG, buzz.load_config)
        gateway = workflow.load_app_config().gateways["tuzi_text"]
        from ai_gateway.clients.openai_chat_client import OpenAIChatClient
        client = OpenAIChatClient(gateway)
        pool = buzz.RuntimeModelPool(gateway, config.model, [], enabled=False)
        source_task = {
            "task_id": "batch:sku",
            "sku": "sku",
            "next_task_payload": {
                "task_id": "batch:sku",
                "precheck_status": "failed",
                "precheck_errors": ["missing image url"],
            },
        }
        with patch.object(buzz, "_call_model", side_effect=AssertionError("must not call provider")):
            record = buzz.call_one(1, 1, source_task, config, client, "tuzi_text", pool)
        self.assertEqual(record.status, "failed_permanent")
        self.assertEqual(record.error_code, "ReferenceImageMissing")

    def test_valid_full_output_repairs_stale_status_and_loads_prompts(self):
        payload = {
            "image_plan": [
                {"image_number": number, "ai_image_generation_prompt": f"prompt {number}"}
                for number in range(1, 7)
            ],
            "global_prompt_restrictions": {"rule": ["keep product accurate"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            full_output = root / "sku__gpt-5.6-luna.json"
            full_output.write_text(json.dumps(payload), encoding="utf-8")
            stale_row = {
                "task_id": "batch:sku",
                "sku": "sku",
                "status": "invalid",
                "validation_status": "failed",
                "error_message": "response JSON is not an object",
                "full_output_path": str(full_output),
            }
            model_results = root / "model_results.jsonl"
            model_results.write_text(json.dumps(stale_row) + "\n", encoding="utf-8")

            normalized = buzz.normalize_result_row(stale_row)
            self.assertEqual(normalized["status"], "success")
            self.assertEqual(normalized["validation_status"], "passed")
            self.assertEqual(normalized["image_plan_count"], 6)
            self.assertIsNone(normalized["error_message"])

            prompt_map = images.load_prompt_map(model_results)
            self.assertEqual(set(prompt_map["sku"]), set(range(1, 7)))
            self.assertIn("prompt 1", prompt_map["sku"][1])

            source_task = {
                "task_id": "batch:sku",
                "sku": "sku",
                "row_number": 2,
                "next_task_payload": {"task_id": "batch:sku", "batch_id": "batch", "metadata": {"sku": "sku"}},
            }
            config = workflow.load_stage_config(workflow.CALL_MODEL_CONFIG, buzz.load_config)
            config.full_outputs_dir = str(root)
            recovered, count = buzz.recover_valid_full_outputs(
                [], [source_task], config, ["gpt-5.6-luna"], "tuzi_text"
            )
            self.assertEqual(count, 1)
            self.assertEqual(recovered[0]["status"], "success")

            checkpoint = root / "checkpoint.jsonl"
            buzz.append_jsonl_row(recovered[0], checkpoint)
            self.assertEqual(buzz.read_jsonl(checkpoint)[0]["task_id"], "batch:sku")

    def test_no_duplicate_stage_retry_counts(self):
        for path in (workflow.GENERATE_MAIN_CONFIG, workflow.GENERATE_IMAGES_CONFIG, workflow.CALL_MODEL_CONFIG):
            retry = json.loads(path.read_text(encoding="utf-8-sig")).get("retry", {})
            self.assertNotIn("max_submit_retries", retry)
            self.assertNotIn("max_retries", retry)

    def test_all_stages_resolve(self):
        for path in (TASK / "stages").glob("*/config.json"):
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            self.assertNotIn("output", raw)
            self.assertNotIn("excel_path", raw.get("input", {}))
            effective = workflow.load_stage_data(path)
            self.assertTrue(effective["output"])
            self.assertTrue(all(str(workflow.batch_root()) in v for v in effective["output"].values()))

    def test_active_image_parameters(self):
        for path, apply in ((workflow.GENERATE_MAIN_CONFIG, workflow.apply_batch_to_main_image_config),
                            (workflow.GENERATE_IMAGES_CONFIG, workflow.apply_batch_to_image_config)):
            data = workflow.load_stage_data(path)
            data["execution"]["model"]["quality"] = "high"
            data["execution"]["model"]["size"] = "1536x1024"
            config = apply(images.load_config(path, config_data=data))
            self.assertEqual(config.quality, "high")
            self.assertEqual(config.size, "1536x1024")
            self.assertEqual(config.gateway, workflow.image_provider())

    def test_removed_gateway_is_rejected(self):
        path = workflow.GENERATE_MAIN_CONFIG
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        raw["execution"]["gateway"] = {"name": "mxapi"}
        original = Path.read_text
        def read(p, *args, **kwargs):
            return json.dumps(raw) if p == path else original(p, *args, **kwargs)
        with patch.object(Path, "read_text", read), self.assertRaises(ValueError):
            workflow.load_stage_data(path)

    def test_upload_only_batch_does_not_imply_mxapi(self):
        from ai_gateway.clients.image_batch import check_batch_provider
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "batch"
            upload_dir = root / "05_upload_oss"
            upload_dir.mkdir(parents=True)
            (upload_dir / "final.xlsx").write_bytes(b"placeholder")
            self.assertEqual(check_batch_provider(root, "tuzi", bind=True), "tuzi")
            marker = json.loads((root / "image_provider.json").read_text(encoding="utf-8"))
            self.assertEqual(marker["provider"], "tuzi")

    def test_generation_record_is_authoritative_for_image_provider(self):
        from ai_gateway.clients.image_batch import check_batch_provider
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "batch"
            generation_dir = root / "04_generate_images"
            generation_dir.mkdir(parents=True)
            (generation_dir / "image_generation_results.jsonl").write_text(
                json.dumps({"sku": "sku", "provider": "mxapi"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                check_batch_provider(root, "tuzi")

    def test_source_is_required(self):
        with patch.object(workflow, "load_task_config", return_value={"image_provider": "tuzi"}):
            with self.assertRaises(ValueError):
                workflow.load_stage_data(workflow.GET_PROMPT_CONFIG)

    def test_batch_stats_uses_desired_count_not_candidate_count(self):
        from scripts.statistics import batch_stats
        config = {
            "image_selection": {
                "desired_count": 5,
                "image_type_order": ["main", "sub1", "sub2", "sub3", "sub4", "sub5"],
            }
        }
        with patch.object(batch_stats, "load_task_config", return_value=config):
            self.assertEqual(batch_stats.image_count_settings(), (6, 5))

    def test_all_loaders_and_batch_override(self):
        for path, module in ((workflow.GET_PROMPT_CONFIG, prompts), (workflow.CALL_MODEL_CONFIG, buzz),
                             (workflow.GENERATE_MAIN_CONFIG, images), (workflow.UPLOAD_OSS_CONFIG, oss)):
            self.assertTrue(workflow.load_stage_config(path, module.load_config).name)
        config = workflow.apply_batch_to_oss_config(
            workflow.load_stage_config(workflow.UPLOAD_OSS_CONFIG, oss.load_config), "test_other_batch")
        self.assertIn("test_other_batch", config.input_excel_path)
        self.assertEqual(config.key_template, workflow.load_task_config()["oss"]["key_template"])
        self.assertEqual(config.concurrency, workflow.task_execution()["oss_concurrency"])

    def test_text_stage_uses_platform_neutral_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            batches = Path(tmp)
            with patch.object(workflow, "BATCHES_ROOT", batches):
                self.assertEqual(workflow.batch_paths("new")["model_results"].parent.name, "02_call_prompt_model")
        with patch.object(workflow, "load_task_config", return_value={"workflow": {"call_prompt_model": True}}):
            switches = workflow.workflow_switches()
            self.assertTrue(switches["call_prompt_model"])

    def test_legacy_replace_config_still_loads(self):
        path = ROOT / "subtasks/walmart_image_replace/stages/generate_images/config.json"
        config = images.load_config(path)
        self.assertEqual(config.provider, "mxapi")
        self.assertEqual(config.gateway, "mxapi")

    def test_full_previews_without_network_or_batch_writes(self):
        original = workflow.load_task_config()
        for provider in ("tuzi", "mxapi"):
            with tempfile.TemporaryDirectory() as tmp:
                batch_root = Path(tmp) / "batches"
                with patch.object(workflow, "BATCHES_ROOT", batch_root), \
                     patch.object(workflow, "load_task_config", return_value={**original, "image_provider": provider}), \
                     patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")), \
                     patch.object(sys, "argv", ["00_full_workflow.py", "--dry-run"]), \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    runpy.run_path(str(TASK / "00_full_workflow.py"), run_name="__main__")
                self.assertIn(provider, output.getvalue())
                self.assertFalse(batch_root.exists())


if __name__ == "__main__":
    unittest.main()
