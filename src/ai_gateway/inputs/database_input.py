"""Database input contract.

Concrete database implementations can map rows to AiTask and write AiResult back.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ai_gateway.models import AiResult, AiTask


class TaskRepository(ABC):
    @abstractmethod
    def fetch_pending(self, limit: int = 100) -> list[AiTask]:
        raise NotImplementedError

    @abstractmethod
    def fetch_retryable_failed(self, batch_id: str, limit: int = 100) -> list[AiTask]:
        """Return failed tasks that are safe to retry for one batch."""
        raise NotImplementedError

    @abstractmethod
    def mark_running(self, task: AiTask) -> None:
        raise NotImplementedError

    @abstractmethod
    def mark_result(self, result: AiResult) -> None:
        raise NotImplementedError
