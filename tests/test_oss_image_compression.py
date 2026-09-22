import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_gateway.subtasks.oss_upload_images import (
    CheckpointStore,
    OssUploadConfig,
    prepare_upload_image,
    process_one,
    process_rows,
)


def config(root: Path) -> OssUploadConfig:
    return OssUploadConfig(
        name="test", project_root=str(root), input_excel_path="", input_sheet_name="Sheet1",
        download_dir=str(root), output_excel_path="", output_results_path="",
        checkpoint_path=str(root / "checkpoint.jsonl"), columns={}, oss_prefix="",
        key_template="develop/{sku}/{image_name}.{extension}", output_format="jpeg",
        jpeg_quality=95, jpeg_subsampling=0, jpeg_optimize=True,
        transparent_policy="keep_png", delete_source_after_upload=True,
    )


class CompressionTests(unittest.TestCase):
    def test_checkpoint_appends_and_legacy_last_state_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cp.jsonl"
            path.write_text(
                '{"sku":"sku","image_name":"image","status":"failed"}\n',
                encoding="utf-8",
            )
            store = CheckpointStore(path)
            from ai_gateway.subtasks.oss_upload_images import OssUploadRecord
            store.upsert(OssUploadRecord(
                row_number=2, sku="sku", image_name="image", status="success",
                local_path="image.jpg", oss_key="key", oss_url="https://example/key",
                file_size=10, error_message=None, retryable=False, created_at="now",
            ))
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)
            self.assertEqual(CheckpointStore(path).rows()[0]["status"], "success")

    def test_forced_stop_trailing_partial_line_keeps_prior_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cp.jsonl"
            path.write_text(
                '{"sku":"sku","image_name":"image","status":"success"}\n'
                '{"sku":"interrupted"',
                encoding="utf-8",
            )
            self.assertEqual(CheckpointStore(path).rows()[0]["status"], "success")
            from ai_gateway.subtasks.mxapi_generate_images import read_jsonl_if_exists as read_generation
            self.assertEqual(read_generation(path)[0]["status"], "success")

    def test_opaque_png_becomes_same_size_jpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "image.png"
            Image.new("RGB", (80, 60), (30, 80, 120)).save(source)
            output, extension = prepare_upload_image(source, config(Path(tmp)))
            self.assertEqual(extension, "jpg")
            self.assertEqual(Image.open(output).size, (80, 60))
            self.assertTrue(source.exists())

    def test_transparent_png_stays_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "image.png"
            Image.new("RGBA", (20, 20), (1, 2, 3, 0)).save(source)
            output, extension = prepare_upload_image(source, config(Path(tmp)))
            self.assertEqual((output, extension), (source, "png"))

    def test_source_deleted_only_after_successful_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "image.png"
            Image.new("RGB", (40, 40), "white").save(source)
            row = {"row_number": 2, "sku": "sku", "image_name": "image",
                   "local_path": str(root / "image.jpg"), "source_path": str(source),
                   "oss_key": "develop/sku/image.jpg"}

            class Client:
                def upload_file(self, local_path, key, overwrite=True):
                    self.key = key
                    return {"success": True, "size": Path(local_path).stat().st_size}
                def public_url(self, key):
                    return "https://example/" + key

            client = Client()
            record = process_one(1, 1, row, config(root), client, CheckpointStore(root / "cp.jsonl"))
            self.assertEqual(record.status, "success")
            self.assertTrue(record.local_path.endswith(".jpg"))
            self.assertTrue(record.oss_key.endswith(".jpg"))
            self.assertFalse(source.exists())
            self.assertTrue(Path(record.local_path).exists())

    def test_generation_paths_append_immediately_and_summary_syncs_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "image.png"
            Image.new("RGB", (40, 40), "white").save(source)
            generation = root / "image_generation_results.jsonl"
            checkpoint = root / "image_generation_checkpoint.jsonl"
            original = {
                "row_number": 2, "sku": "sku", "image_name": "image", "status": "success",
                "downloaded_path": str(source), "file_size": source.stat().st_size,
            }
            import json
            generation.write_text(json.dumps(original) + "\n", encoding="utf-8")
            checkpoint.write_text(json.dumps(original) + "\n", encoding="utf-8")
            cfg = config(root)
            cfg.image_results_path = str(generation)
            row = {"row_number": 2, "sku": "sku", "image_name": "image",
                   "local_path": str(root / "image.jpg"), "source_path": str(source),
                   "oss_key": "develop/sku/image.jpg"}

            class Client:
                def upload_file(self, local_path, key, overwrite=True):
                    return {"success": True, "size": Path(local_path).stat().st_size}
                def public_url(self, key):
                    return "https://example/" + key

            records = process_rows([row], cfg, Client(), CheckpointStore(root / "oss.jsonl"))
            self.assertEqual(records[0].status, "success")
            self.assertFalse(source.exists())
            self.assertEqual(len(checkpoint.read_text(encoding="utf-8").splitlines()), 2)
            saved = json.loads(generation.read_text(encoding="utf-8").splitlines()[0])
            self.assertTrue(saved["downloaded_path"].endswith("image.jpg"))
            self.assertTrue(Path(saved["downloaded_path"]).is_file())

    def test_successful_upload_repairs_stale_cross_cycle_generation_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "image.png"
            Image.new("RGB", (40, 40), "white").save(source)
            generation = root / "image_generation_results.jsonl"
            checkpoint = root / "image_generation_checkpoint.jsonl"
            stale = {
                "row_number": 2, "sku": "sku", "image_name": "image",
                "status": "submitted", "task_id": "task-paid",
                "downloaded_path": None, "file_size": None,
            }
            import json
            generation.write_text(json.dumps(stale) + "\n", encoding="utf-8")
            checkpoint.write_text(json.dumps(stale) + "\n", encoding="utf-8")
            cfg = config(root)
            cfg.image_results_path = str(generation)
            row = {"row_number": 2, "sku": "sku", "image_name": "image",
                   "local_path": str(root / "image.jpg"), "source_path": str(source),
                   "oss_key": "develop/sku/image.jpg"}

            class Client:
                def upload_file(self, local_path, key, overwrite=True):
                    return {"success": True, "size": Path(local_path).stat().st_size}
                def public_url(self, key):
                    return "https://example/" + key

            process_rows([row], cfg, Client(), CheckpointStore(root / "oss.jsonl"))
            latest = json.loads(checkpoint.read_text(encoding="utf-8").splitlines()[-1])
            summary = json.loads(generation.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(latest["status"], "success")
            self.assertEqual(summary["status"], "success")
            self.assertEqual(latest["task_id"], "task-paid")


if __name__ == "__main__":
    unittest.main()
