"""Gateway adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ai_gateway.config.loader import GatewayConfig
from ai_gateway.models import AiResult, AiTask


class GatewayAdapter(ABC):
    """Base class for all gateway adapters."""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    @abstractmethod
    def build_request(self, task: AiTask) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def send(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def parse_response(self, task: AiTask, response_payload: dict[str, Any]) -> AiResult:
        raise NotImplementedError

    def call(self, task: AiTask) -> AiResult:
        payload = self.build_request(task)
        response = self.send(payload)
        return self.parse_response(task, response)
