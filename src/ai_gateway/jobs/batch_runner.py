"""Batch processing utilities."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from ai_gateway.clients.gateway_client import GatewayClient
from ai_gateway.inputs.database_input import TaskRepository
from ai_gateway.logging.jsonl_logger import JsonlLogger
from ai_gateway.models import AiResult, AiTask, BatchSummary
from ai_gateway.validators.result_validator import validate_result


class BatchRunner:
    def __init__(self, client: GatewayClient, logger: JsonlLogger | None = None) -> None:
        self.client = client
        self.logger = logger

    def run(
        self,
        tasks: Iterable[AiTask],
        concurrency: int = 1,
        batch_id: str | None = None,
        mode: str = "batch",
        repository: TaskRepository | None = None,
    ) -> list[AiResult]:
        started_at = datetime.now()
        task_list = list(tasks)
        if batch_id:
            for task in task_list:
                task.batch_id = task.batch_id or batch_id

        if concurrency <= 1:
            results = [self._call_one(task, repository=repository) for task in task_list]
        else:
            results = []
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                future_map = {
                    executor.submit(self._call_one, task, repository): task
                    for task in task_list
                }
                for future in as_completed(future_map):
                    results.append(future.result())

        self._write_summary(
            batch_id=batch_id or self._infer_batch_id(task_list),
            mode=mode,
            results=results,
            started_at=started_at,
        )
        return results

    def retry_failed_batch(
        self,
        repository: TaskRepository,
        batch_id: str,
        limit: int = 100,
        concurrency: int = 1,
    ) -> list[AiResult]:
        tasks = repository.fetch_retryable_failed(batch_id=batch_id, limit=limit)
        for task in tasks:
            task.batch_id = batch_id
            task.attempt += 1
        return self.run(
            tasks,
            concurrency=concurrency,
            batch_id=batch_id,
            mode="retry",
            repository=repository,
        )

    def _call_one(
        self,
        task: AiTask,
        repository: TaskRepository | None = None,
    ) -> AiResult:
        if repository:
            repository.mark_running(task)
        result = self.client.call(task)
        result = validate_result(result, task)
        if self.logger:
            self.logger.write_result(result)
        if repository:
            repository.mark_result(result)
        return result

    def _write_summary(
        self,
        batch_id: str | None,
        mode: str,
        results: list[AiResult],
        started_at: datetime,
    ) -> None:
        if not self.logger:
            return
        summary = BatchSummary(
            batch_id=batch_id or "unknown",
            mode="retry" if mode == "retry" else "batch",
            total_count=len(results),
            success_count=sum(1 for item in results if item.status == "success"),
            failed_count=sum(1 for item in results if item.status == "failed"),
            retryable_failed_count=sum(
                1 for item in results if item.status == "failed" and item.retryable
            ),
            started_at=started_at,
            finished_at=datetime.now(),
        )
        self.logger.write_summary(summary)

    @staticmethod
    def _infer_batch_id(tasks: list[AiTask]) -> str | None:
        for task in tasks:
            if task.batch_id:
                return task.batch_id
        return None
