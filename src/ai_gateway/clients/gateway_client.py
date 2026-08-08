"""Gateway client facade used by business code."""

from __future__ import annotations

from ai_gateway.adapters import buzz as _buzz  # noqa: F401 - registers built-in adapters
from ai_gateway.adapters.registry import get_adapter_class
from ai_gateway.config.loader import AppConfig
from ai_gateway.models import AiResult, AiTask


class GatewayClient:
    """Routes normalized tasks to configured gateway adapters."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def call(self, task: AiTask) -> AiResult:
        gateway_name = task.gateway or self.config.default_gateway
        gateway_config = self.config.gateways[gateway_name]
        adapter_cls = get_adapter_class(gateway_config.type)
        adapter = adapter_cls(gateway_config)
        if task.model is None:
            task.model = self.config.default_model
        return adapter.call(task)
