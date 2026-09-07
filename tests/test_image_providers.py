"""Offline protocol fixtures; no live keys or paid API requests."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_gateway.clients.image_providers import (
    MxapiImageAdapter, TuziImageAdapter, ImageProtocolError, SubmissionUnknown,
    create_image_adapter,
)
from ai_gateway.clients.image_batch import check_batch_provider
from ai_gateway.config.loader import GatewayConfig
from ai_gateway.subtasks import mxapi_generate_images as engine


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.cfg = SimpleNamespace(model="gpt-image-2", aspect_ratio="1:1", resolution="1K",
                                   size=None, quality="low", provider="tuzi",
                                   max_submit_retries=3, submit_delay_seconds=0,
                                   retry_delay_seconds=0, max_wait_seconds=2, poll_interval_seconds=0)
        self.gateway = GatewayConfig("tuzi", "tuzi", "https://example.test", api_key_value="test-only", max_retries=2)
        self.tuzi = TuziImageAdapter(self.gateway)
        self.mx = MxapiImageAdapter(self.gateway, "/submit", "/query")

    def test_payloads(self):
        self.assertEqual(self.tuzi.build_payload("p", "https://img.test/a.png", self.cfg),
                         dict(model="gpt-image-2", prompt="p", image=["https://img.test/a.png"],
                              size="1024x1024", quality="low", n=1, output_format="png", response_format="url"))
        self.assertEqual(self.mx.build_payload("p", "ref", self.cfg),
                         dict(prompt="p", aspect_ratio="1:1", quality="low", resolution="1K", reference_images=["ref"]))

    def test_size_not_silently_downgraded(self):
        self.cfg.resolution = "4K"
        with self.assertRaises(ImageProtocolError):
            self.tuzi.build_payload("p", "r", self.cfg)

    def test_submission_parsers(self):
        self.assertEqual(self.tuzi.parse_submit({"id": "task_123", "status": "queued"}), "task_123")
        self.assertEqual(self.mx.parse_submit({"code": 200, "data": {"task_id": "mx123"}}), "mx123")
        with self.assertRaises(SubmissionUnknown):
            self.tuzi.parse_submit({"data": [{"url": "https://image.test/x"}]})

    def test_pending_failure_unknown(self):
        for status in ("queued", "not_start", "submitted", "in_progress"):
            self.assertEqual(self.tuzi.parse_query({"status": status}).status, "pending")
        self.assertEqual(self.tuzi.parse_query({"status": "failure", "error": "bad"}).error, "bad")
        for status in ("expired", "new_unknown", None):
            with self.assertRaises(ImageProtocolError):
                self.tuzi.parse_query({"status": status})

    def test_completed(self):
        payload = {"status": "completed", "status_code": 200,
                   "result": {"data": [{"url": "https://image.test/x.png"}]}}
        self.assertEqual(self.tuzi.parse_query(payload).urls, ["https://image.test/x.png"])
        for result in ({}, {"error": "bad"}, {"data": [{"b64_json": "abc"}]}, {"data": []}):
            with self.assertRaises(ImageProtocolError):
                self.tuzi.parse_query(dict(payload, result=result))
        with self.assertRaises(ImageProtocolError):
            self.tuzi.parse_query(dict(payload, status_code=500))

    def test_mx_results_unchanged(self):
        payload = {"code": 200, "data": {"status": "completed",
                   "result": {"source_images": ["a", "b"], "proxy_images": ["a"], "images": ["c"]}}}
        self.assertEqual(self.mx.parse_query(payload).urls, ["a", "b", "c"])
        self.assertEqual(engine.collect_image_urls(payload), ["a", "b", "c"])
        self.assertEqual(self.mx.parse_query({"code": 200, "data": {"status": "failed", "error_msg": "x"}}).error, "x")

    def test_tuzi_query_id_parameter(self):
        with patch("ai_gateway.clients.image_providers.requests.get") as get:
            get.return_value.json.return_value = {"status": "queued"}
            self.tuzi.query("task_123")
            self.assertEqual(get.call_args.kwargs["params"], {"id": "task_123"})
            self.assertTrue(get.call_args.args[0].endswith("/get-async"))

    def test_unknown_submission_retries_twice(self):
        with patch.object(self.tuzi, "submit", side_effect=TimeoutError("timeout")) as submit:
            with self.assertRaises(SubmissionUnknown):
                engine.submit_with_retry(self.tuzi, "p", "r", self.cfg)
            self.assertEqual(submit.call_count, 3)

    def test_mx_retry_unchanged(self):
        self.cfg.provider = "mxapi"
        with patch.object(self.mx, "submit", side_effect=[RuntimeError("503"), ({"code": 200, "data": {"task_id": "x"}}, 1)]) as submit:
            self.assertEqual(engine.submit_with_retry(self.mx, "p", "r", self.cfg), ("x", 1))
            self.assertEqual(submit.call_count, 2)

    def test_poll_normalized(self):
        payload = {"status": "completed", "result": {"data": [{"url": "https://image.test/x"}]}}
        with patch.object(self.tuzi, "query", side_effect=[({"status": "queued"}, 1), (payload, 1)]):
            result, count, _ = engine.poll_until_done(self.tuzi, "id", self.cfg)
        self.assertEqual(count, 2)
        self.assertEqual(result, payload)

    def worker_setup(self, tmp):
        self.cfg.prompt_mode = "fixed"
        self.cfg.poll_existing_task_id = True
        self.cfg.max_download_retries = 1
        self.cfg.download_timeout_seconds = 1
        self.cfg.download_dir = tmp
        self.cfg.raw_responses_dir = tmp
        row = dict(row_number=2, sku="sku1", image_name="new_main_sku1",
                   image_number=None, reference_image="https://image.test/ref", prompt="p")
        return row, engine.CheckpointStore(Path(tmp) / "checkpoint.jsonl", "tuzi")

    def test_worker_checkpoint_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, checkpoint = self.worker_setup(tmp)
            completed = {"status": "completed", "result": {"data": [{"url": "https://image.test/out"}]}}
            with patch.object(self.tuzi, "submit", return_value=({"id": "task1"}, 1)) as submit, \
                 patch.object(self.tuzi, "query", return_value=(completed, 1)), \
                 patch.object(self.tuzi, "download", return_value=10):
                record = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
                self.assertEqual(record.status, "success")
                self.assertEqual(record.provider, "tuzi")
                history = [json.loads(line) for line in checkpoint.path.read_text(encoding="utf-8").splitlines()]
                self.assertEqual([r["status"] for r in history], ["submission_unknown", "submitted", "success"])
                self.assertTrue(all(r["provider"] == "tuzi" for r in history))
                row["task_id"] = "task1"
                resumed = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
                self.assertEqual(resumed.status, "success")
                self.assertEqual(submit.call_count, 1)

    def test_worker_unknown_is_durable(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, checkpoint = self.worker_setup(tmp)
            with patch.object(self.tuzi, "submit", side_effect=TimeoutError("timeout")) as submit:
                record = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
            self.assertEqual(record.status, "failed")
            self.assertTrue(record.retryable)
            self.assertEqual(submit.call_count, 3)
            history = [json.loads(line) for line in checkpoint.path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(history[-1]["status"], "failed")

    def test_tuzi_gateway_controls_retry_count(self):
        self.gateway.max_retries = 0
        self.cfg.max_submit_retries = 9
        with patch.object(self.tuzi, "submit", side_effect=TimeoutError("timeout")) as submit:
            with self.assertRaises(SubmissionUnknown):
                engine.submit_with_retry(self.tuzi, "p", "r", self.cfg)
            self.assertEqual(submit.call_count, 1)

    def test_mx_gateway_controls_retry_count(self):
        self.cfg.provider = "mxapi"
        self.cfg.max_submit_retries = 99
        for retries in (0, 2):
            self.gateway.max_retries = retries
            with patch.object(self.mx, "submit", side_effect=TimeoutError("timeout")) as submit:
                with self.assertRaises(RuntimeError):
                    engine.submit_with_retry(self.mx, "p", "r", self.cfg)
                self.assertEqual(submit.call_count, retries + 1)

    def test_tuzi_stops_retrying_after_id(self):
        with patch.object(self.tuzi, "submit", side_effect=[TimeoutError("timeout"), ({"id": "task_ok"}, 1)]) as submit:
            self.assertEqual(engine.submit_with_retry(self.tuzi, "p", "r", self.cfg), ("task_ok", 1))
            self.assertEqual(submit.call_count, 2)

    def test_checkpoint_failure_prevents_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, checkpoint = self.worker_setup(tmp)
            with patch.object(checkpoint, "append_locked", side_effect=engine.CheckpointWriteError("disk full")), \
                 patch.object(self.tuzi, "submit") as submit:
                with self.assertRaises(engine.CheckpointWriteError):
                    engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
                submit.assert_not_called()

    def test_factory_rejects_unknown(self):
        with self.assertRaises(ValueError):
            create_image_adapter("other", self.gateway, "", "")

    def test_batch_preview_and_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "batch"
            check_batch_provider(root, "tuzi")
            self.assertFalse(root.exists())
            check_batch_provider(root, "tuzi", bind=True)
            check_batch_provider(root, "tuzi")
            with self.assertRaises(RuntimeError):
                check_batch_provider(root, "mxapi")

    def test_legacy_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "04_generate_images" / "image_generation_checkpoint.jsonl"
            old.parent.mkdir()
            old.write_text("{}\n")
            check_batch_provider(root, "mxapi")
            with self.assertRaises(RuntimeError):
                check_batch_provider(root, "tuzi")
            self.assertFalse((root / "image_provider.json").exists())

    def test_both_stage_configs_share_switch(self):
        spec = importlib.util.spec_from_file_location("prompt_workflow_test", ROOT / "subtasks/walmart_image_prompt/workflow_common.py")
        workflow = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(workflow)
        original = workflow.load_task_config()
        for provider in ("mxapi", "tuzi"):
            with patch.object(workflow, "load_task_config", return_value={**original, "image_provider": provider}):
                for path, apply in ((workflow.GENERATE_IMAGES_CONFIG, workflow.apply_batch_to_image_config),
                                    (workflow.GENERATE_MAIN_CONFIG, workflow.apply_batch_to_main_image_config)):
                    config = apply(workflow.load_stage_config(path, engine.load_config))
                    self.assertEqual(config.provider, provider)
                    self.assertEqual(config.gateway, provider)
                    self.assertEqual(config.submit_endpoint, "/async/v1/images/generations" if provider == "tuzi" else "/api/v2/gpt-image-2")


if __name__ == "__main__":
    unittest.main()
