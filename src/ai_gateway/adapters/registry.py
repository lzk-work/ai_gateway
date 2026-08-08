"""Adapter registry."""

from __future__ import annotations

from ai_gateway.adapters.base import GatewayAdapter

_ADAPTERS: dict[str, type[GatewayAdapter]] = {}


def register_adapter(gateway_type: str, adapter_cls: type[GatewayAdapter]) -> None:
    _ADAPTERS[gateway_type] = adapter_cls


def get_adapter_class(gateway_type: str) -> type[GatewayAdapter]:
    try:
        return _ADAPTERS[gateway_type]
    except KeyError as exc:
        known = ", ".join(sorted(_ADAPTERS)) or "none"
        raise KeyError(f"Unknown gateway type '{gateway_type}'. Registered: {known}") from exc
