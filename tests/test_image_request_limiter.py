from concurrent.futures import ThreadPoolExecutor
import threading
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_gateway.subtasks.mxapi_generate_images import RateLimitedImageClient, ImageDownloadRateLimited, download_with_retry
from types import SimpleNamespace
import pytest
from unittest.mock import patch


def test_submissions_and_queries_share_start_interval():
    starts = []
    lock = threading.Lock()

    class Client:
        gateway = "gateway"

        def submit(self, payload):
            with lock:
                starts.append(time.monotonic())
            return payload

        def query(self, task_id):
            return self.submit(task_id)

        def download(self, url, path, **kwargs):
            return self.submit(url)

    client = RateLimitedImageClient(Client(), 0.03)
    assert client.gateway == "gateway"
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(client.submit if i % 2 else client.query, i) for i in range(3)]
        futures.append(pool.submit(client.download, 3, "unused"))
        assert [f.result() for f in futures] == list(range(4))
    assert all(b - a >= 0.025 for a, b in zip(starts, starts[1:]))


def test_download_429_stops_only_current_image_without_retries():
    calls = []

    class Client:
        def download(self, url, path, **kwargs):
            calls.append(url)
            if url == "limited":
                raise RuntimeError("HTTP 429: Too Many Requests")
            return 100

    config = SimpleNamespace(max_download_retries=5, download_timeout_seconds=60, retry_delay_seconds=3)
    client = Client()
    with pytest.raises(ImageDownloadRateLimited):
        download_with_retry(client, ["limited", "alternate"], Path("unused"), config)
    assert calls == ["limited"]
    assert download_with_retry(client, ["healthy"], Path("unused"), config) == (100, "healthy")


def test_download_uses_five_attempts_with_four_fixed_waits():
    calls = []

    class Client:
        def download(self, url, path, **kwargs):
            calls.append(url)
            raise RuntimeError("connection reset")

    config = SimpleNamespace(max_download_retries=5, download_timeout_seconds=60,
                             retry_delay_seconds=10, download_retry_delay_seconds=3)
    with patch("ai_gateway.subtasks.mxapi_generate_images.time.sleep") as sleep:
        with pytest.raises(RuntimeError, match="download failed"):
            download_with_retry(Client(), ["image"], Path("unused"), config)
    assert len(calls) == 5
    assert [call.args for call in sleep.call_args_list] == [(3,), (3,), (3,), (3,)]
