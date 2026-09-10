"""Offline protocol fixtures; no live keys or paid API requests."""
import importlib.util
import base64
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
    ImagePollResult, MxapiImageAdapter, TuziImageAdapter, ImageProtocolError, SubmissionUnknown,
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
                                   retry_delay_seconds=0, query_retry_delay_seconds=0,
                                   max_wait_seconds=2, poll_interval_seconds=0)
        self.gateway = GatewayConfig("tuzi", "tuzi", "https://example.test", api_key_value="test-only", max_retries=2)
        self.tuzi = TuziImageAdapter(self.gateway)
        self.mx = MxapiImageAdapter(self.gateway, "/submit", "/query")

    def test_payloads(self):
        self.assertEqual(self.tuzi.build_payload("p", "https://img.test/a.png", self.cfg),
                         dict(model="gpt-image-2", prompt="p",
                              input_reference=["https://img.test/a.png"], size="1024x1024"))
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
        for status in ("queued", "not_start", "submitted", "in_progress", "expired"):
            self.assertEqual(self.tuzi.parse_query({"status": status}).status, "pending")
        self.assertEqual(self.tuzi.parse_query({"status": "failure", "error": "bad"}).error, "bad")
        for status in ("new_unknown", None):
            with self.assertRaises(ImageProtocolError):
                self.tuzi.parse_query({"status": status})

    def test_expired_payload_continues_polling_same_task(self):
        completed = {"status": "completed", "video_url": "https://image.test/x"}
        with patch.object(self.tuzi, "query", side_effect=[
                ({"id": "task_existing", "status": "expired", "message": "async task result has been deleted"}, 1),
                (completed, 1),
             ]) as query:
            result, count, _ = engine.poll_until_done(self.tuzi, "task_existing", self.cfg)
        self.assertEqual(result, completed)
        self.assertEqual(count, 2)
        self.assertEqual(query.call_count, 2)

    def test_completed(self):
        payload = {"id": "task_1", "status": "completed", "progress": 100,
                   "video_url": "https://image.test/result.png"}
        self.assertEqual(self.tuzi.parse_query(payload).urls, ["https://image.test/result.png"])
        with self.assertRaisesRegex(ImageProtocolError, "no valid video_url"):
            self.tuzi.parse_query({"status": "completed", "video_url": ""})

    def test_base64_result_is_saved_without_http_download(self):
        encoded = base64.b64encode(b"png-test-data").decode("ascii")
        parsed = ImagePollResult("completed", b64_images=[encoded])
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.tuzi, "download") as download:
            path = Path(tmp) / "image.png"
            size, used_url = engine.save_image_result(self.tuzi, parsed, path, self.cfg)
            self.assertEqual(path.read_bytes(), b"png-test-data")
            self.assertEqual(size, len(b"png-test-data"))
            self.assertIsNone(used_url)
            download.assert_not_called()

    def test_invalid_base64_is_rejected_when_saving(self):
        parsed = ImagePollResult("completed", b64_images=["not-valid-base64"])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                engine.save_image_result(self.tuzi, parsed, Path(tmp) / "image.png", self.cfg)

    def test_mx_results_unchanged(self):
        payload = {"code": 200, "data": {"status": "completed",
                   "result": {"source_images": ["a", "b"], "proxy_images": ["a"], "images": ["c"]}}}
        self.assertEqual(self.mx.parse_query(payload).urls, ["a", "b", "c"])
        self.assertEqual(engine.collect_image_urls(payload), ["a", "b", "c"])
        self.assertEqual(self.mx.parse_query({"code": 200, "data": {"status": "failed", "error_msg": "x"}}).error, "x")

    def test_tuzi_video_query_path(self):
        with patch("ai_gateway.clients.image_providers.requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"status": "queued"}
            self.tuzi.query("task_123")
            self.assertNotIn("params", get.call_args.kwargs)
            self.assertTrue(get.call_args.args[0].endswith("/v1/videos/task_123"))

    def test_tuzi_query_does_not_fall_back_to_legacy_endpoint(self):
        response = SimpleNamespace(status_code=400, text='{"code":"invalid_channel_id"}')
        with patch("ai_gateway.clients.image_providers.requests.get", return_value=response) as get:
            with self.assertRaisesRegex(RuntimeError, "invalid_channel_id"):
                self.tuzi.query("task_from_other_protocol")
        self.assertEqual(get.call_count, 1)
        self.assertTrue(get.call_args.args[0].endswith("/v1/videos/task_from_other_protocol"))

    def test_tuzi_submit_uses_repeated_url_reference_parts(self):
        response = SimpleNamespace(status_code=200, json=lambda: {"id": "task_1"}, text="")
        payload = self.tuzi.build_payload(
            "p", ["https://img.test/a.png", "https://img.test/b.png"], self.cfg
        )
        with patch("ai_gateway.clients.image_providers.requests.post", return_value=response) as post:
            self.tuzi.submit(payload)
        parts = post.call_args.kwargs["files"]
        references = [part for part in parts if part[0] == "input_reference"]
        self.assertEqual([part[1][1] for part in references],
                         ["https://img.test/a.png", "https://img.test/b.png"])
        self.assertTrue(post.call_args.args[0].endswith("/v1/videos"))

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
        payload = {"status": "completed", "video_url": "https://image.test/x"}
        with patch.object(self.tuzi, "query", side_effect=[({"status": "queued"}, 1), (payload, 1)]):
            result, count, _ = engine.poll_until_done(self.tuzi, "id", self.cfg)
        self.assertEqual(count, 2)
        self.assertEqual(result, payload)

    def test_poll_retries_temporary_query_error_without_resubmitting(self):
        completed = {"status": "completed", "video_url": "https://image.test/x"}
        self.gateway.max_retries = 2
        with patch.object(self.tuzi, "query", side_effect=[RuntimeError("503 Service Unavailable"), (completed, 1)]) as query:
            result, count, _ = engine.poll_until_done(self.tuzi, "task_existing", self.cfg)
        self.assertEqual(result, completed)
        self.assertEqual(count, 1)
        self.assertEqual(query.call_count, 2)

    def test_poll_continues_after_one_exhausted_temporary_query_batch(self):
        completed = {"status": "completed", "video_url": "https://image.test/x"}
        self.gateway.max_retries = 2
        with patch.object(self.tuzi, "query", side_effect=[
                RuntimeError("503 Service Unavailable"),
                RuntimeError("503 Service Unavailable"),
                RuntimeError("503 Service Unavailable"),
                (completed, 1),
             ]) as query:
            result, count, _ = engine.poll_until_done(self.tuzi, "task_existing", self.cfg)
        self.assertEqual(result, completed)
        self.assertEqual(count, 2)
        self.assertEqual(query.call_count, 4)

    def test_exhausted_query_errors_become_pending_with_same_task_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, checkpoint = self.worker_setup(tmp)
            row["task_id"] = "task_existing"
            self.gateway.max_retries = 2
            with patch.object(self.tuzi, "query", side_effect=RuntimeError("503 Service Unavailable")) as query, \
                 patch.object(self.tuzi, "submit") as submit, \
                 patch.object(engine.time, "time", side_effect=[0, 0, 3]), \
                 patch.object(engine.time, "sleep"):
                record = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
            self.assertEqual(record.status, "pending")
            self.assertEqual(record.task_id, "task_existing")
            self.assertEqual(query.call_count, 3)
            submit.assert_not_called()

    def test_expired_query_retries_then_becomes_pending_without_resubmit(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, checkpoint = self.worker_setup(tmp)
            row["task_id"] = "task_expired"
            self.gateway.max_retries = 2
            with patch.object(self.tuzi, "query", side_effect=RuntimeError(
                    "410 Client Error: Gone; {\"status\":\"expired\",\"message\":\"async task result has been deleted\"}"
                 )) as query, patch.object(self.tuzi, "submit") as submit, \
                 patch.object(engine.time, "time", side_effect=[0, 0, 3]), \
                 patch.object(engine.time, "sleep"):
                record = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
            self.assertEqual(record.status, "pending")
            self.assertEqual(record.task_id, "task_expired")
            self.assertEqual(query.call_count, 3)
            submit.assert_not_called()

    def test_expired_query_can_recover_on_retry(self):
        completed = {"status": "completed", "video_url": "https://image.test/out"}
        self.gateway.max_retries = 2
        with patch.object(self.tuzi, "query", side_effect=[
                RuntimeError("410 Client Error: Gone for url: https://api.tu-zi.com/v1/videos/task_existing"),
                (completed, 1),
             ]) as query:
            result, _, _ = engine.poll_until_done(self.tuzi, "task_existing", self.cfg)
        self.assertEqual(result, completed)
        self.assertEqual(query.call_count, 2)

    def test_expired_result_does_not_resubmit_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, checkpoint = self.worker_setup(tmp)
            row.update(task_id="task_new", attempts=1)
            completed = {"status": "completed", "video_url": "https://image.test/gone"}
            with patch.object(self.tuzi, "query", return_value=(completed, 1)), \
                 patch.object(self.tuzi, "download", side_effect=RuntimeError("HTTP 404: gone")), \
                 patch.object(self.tuzi, "submit") as submit:
                record = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
            self.assertEqual(record.status, "failed")
            self.assertFalse(record.retryable)
            self.assertEqual(record.attempts, 1)
            submit.assert_not_called()

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
            completed = {"status": "completed", "video_url": "https://image.test/out"}
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

    def test_deferred_async_submit_saves_id_without_polling(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, checkpoint = self.worker_setup(tmp)
            self.cfg.deferred_async = True
            with patch.object(self.tuzi, "submit", return_value=({"id": "task1"}, 1)) as submit, \
                 patch.object(self.tuzi, "query") as query:
                record = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
            self.assertEqual(record.status, "submitted")
            self.assertEqual(record.task_id, "task1")
            self.assertEqual(submit.call_count, 1)
            query.assert_not_called()

    def test_deferred_async_pending_keeps_existing_id_without_resubmit(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, checkpoint = self.worker_setup(tmp)
            row["task_id"] = "task_existing"
            self.cfg.deferred_async = True
            with patch.object(self.tuzi, "query", return_value=({"status": "queued"}, 1)), \
                 patch.object(self.tuzi, "submit") as submit:
                record = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
            self.assertEqual(record.status, "pending")
            self.assertEqual(record.task_id, "task_existing")
            submit.assert_not_called()

    def test_deferred_async_query_attempts_are_a_hard_total_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, checkpoint = self.worker_setup(tmp)
            row["task_id"] = "task_existing"
            self.cfg.deferred_async = True
            self.cfg.query_attempts_per_cycle = 3
            self.cfg.query_retry_delay_seconds = 5
            with patch.object(self.tuzi, "query", return_value=({"status": "queued"}, 1)) as query, \
                 patch.object(self.tuzi, "submit") as submit, \
                 patch.object(engine.time, "sleep") as sleep:
                record = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
            self.assertEqual(record.status, "pending")
            self.assertEqual(record.task_id, "task_existing")
            self.assertEqual(query.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 5])
            submit.assert_not_called()

    def test_confirmed_failure_resubmits_only_up_to_configured_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            row, checkpoint = self.worker_setup(tmp)
            row.update(task_id="failed_task", attempts=1)
            self.cfg.deferred_async = True
            self.cfg.max_regenerations_per_image = 2
            with patch.object(self.tuzi, "query", return_value=({"status": "failed", "error": "upstream failed"}, 1)), \
                 patch.object(self.tuzi, "submit", return_value=({"id": "replacement_task"}, 1)) as submit:
                record = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
            self.assertEqual(record.status, "submitted")
            self.assertEqual(record.task_id, "replacement_task")
            self.assertEqual(record.attempts, 2)
            self.assertEqual(submit.call_count, 1)

            row.update(task_id="replacement_task", attempts=2)
            with patch.object(self.tuzi, "query", return_value=({"status": "failed", "error": "upstream failed"}, 1)), \
                 patch.object(self.tuzi, "submit") as submit:
                exhausted = engine.process_one(1, 1, row, {}, self.cfg, self.tuzi, checkpoint)
            self.assertEqual(exhausted.status, "failed_exhausted")
            self.assertFalse(exhausted.retryable)
            submit.assert_not_called()

    def test_skipped_fallback_is_reconsidered_if_capacity_reopens(self):
        self.assertFalse(engine.is_terminal_skippable({"status": "skipped"}))

    def test_desired_result_count_distinguishes_candidates_from_target(self):
        rows = [
            {"sku": sku, "image_name": f"new_sub{index}_{sku}"}
            for sku in ("sku1", "sku2")
            for index in range(1, 7)
        ]
        self.assertEqual(len(rows), 12)
        self.assertEqual(engine.desired_result_count(rows, 5), 10)

    def test_sku_target_does_not_shrink_to_remaining_candidate_rows(self):
        self.cfg.prompt_mode = "buzz"
        self.cfg.desired_count = 5
        self.assertEqual(engine.sku_target_count(self.cfg, [{}, {}]), 5)
        self.cfg.prompt_mode = "fixed"
        self.assertEqual(engine.sku_target_count(self.cfg, [{}]), 1)

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

    def test_uncertain_result_pauses_sku_fallback(self):
        base = dict(row_number=2, sku="sku1", image_name="new_sub5_sku1", image_type="type5",
                    image_number=5, reference_image="ref", generated_image_url=None,
                    downloaded_path=None, file_size=None, retryable=True, submit_latency_ms=None,
                    poll_count=0, total_wait_seconds=None)
        pending = engine.ImageGenerationRecord(status="pending", task_id="task1", error_message="PollTimeout: 410", **base)
        unknown = engine.ImageGenerationRecord(status="failed", task_id=None,
                                               error_message="SubmissionUnknown: timeout", **base)
        incomplete = engine.ImageGenerationRecord(status="failed", task_id="task1",
                                                  error_message="ImageProtocolError: no data", **base)
        failed = engine.ImageGenerationRecord(status="failed", task_id="task1",
                                              error_message="TaskFailedError: upstream failed", **base)
        self.assertTrue(engine.should_pause_sku_after_record(pending))
        self.assertTrue(engine.should_pause_sku_after_record(unknown))
        self.assertTrue(engine.should_pause_sku_after_record(incomplete))
        self.assertFalse(engine.should_pause_sku_after_record(failed))

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
                    self.assertEqual(config.submit_endpoint, "/v1/videos" if provider == "tuzi" else "/api/v2/gpt-image-2")


if __name__ == "__main__":
    unittest.main()
