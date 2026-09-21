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


def test_request_intervals_are_independent_per_operation_and_worker_thread():
    starts = {"submit": [], "query": [], "download": []}
    lock = threading.Lock()

    class Client:
        gateway = "gateway"

        def submit(self, payload):
            with lock:
                starts["submit"].append((payload, time.monotonic()))
            return payload

        def query(self, task_id):
            with lock:
                starts["query"].append((task_id, time.monotonic()))
            return task_id

        def download(self, url, path, **kwargs):
            with lock:
                starts["download"].append((url, time.monotonic()))
            return url

    client = RateLimitedImageClient(Client(), 0, 0, 0.03)
    assert client.gateway == "gateway"
    barrier = threading.Barrier(2)

    def download_twice(worker):
        barrier.wait()
        client.download((worker, 1), "unused")
        client.download((worker, 2), "unused")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(download_twice, worker) for worker in range(2)]
        for future in futures:
            future.result()

    per_worker = {}
    for (worker, _), started_at in starts["download"]:
        per_worker.setdefault(worker, []).append(started_at)
    assert all(times[1] - times[0] >= 0.025 for times in per_worker.values())
    first_starts = [times[0] for times in per_worker.values()]
    assert max(first_starts) - min(first_starts) < 0.025


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
