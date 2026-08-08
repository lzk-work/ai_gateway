"""Example retry flow for failed records in one batch.

Replace `YourTaskRepository` with a concrete database implementation.
"""

from ai_gateway.clients.gateway_client import GatewayClient
from ai_gateway.config.loader import load_app_config
from ai_gateway.inputs.database_input import TaskRepository
from ai_gateway.jobs.batch_runner import BatchRunner
from ai_gateway.logging.jsonl_logger import JsonlLogger
from ai_gateway.models import AiResult, AiTask


class YourTaskRepository(TaskRepository):
    def fetch_pending(self, limit: int = 100) -> list[AiTask]:
        raise NotImplementedError

    def fetch_retryable_failed(self, batch_id: str, limit: int = 100) -> list[AiTask]:
        raise NotImplementedError

    def mark_running(self, task: AiTask) -> None:
        raise NotImplementedError

    def mark_result(self, result: AiResult) -> None:
        raise NotImplementedError


config = load_app_config("configs/gateways.yaml", "configs/models.yaml")
client = GatewayClient(config)
logger = JsonlLogger("logs/retry_failed_batch.jsonl")
runner = BatchRunner(client, logger=logger)
repository = YourTaskRepository()

results = runner.retry_failed_batch(
    repository=repository,
    batch_id="B20260805",
    limit=100,
    concurrency=3,
)

print(f"retried={len(results)}")
