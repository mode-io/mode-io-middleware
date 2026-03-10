#!/usr/bin/env python3

from __future__ import annotations

from typing import Any, Dict

from modeio_middleware.core.upstream_client import (
    forward_upstream_json,
    forward_upstream_models_json,
    forward_upstream_stream,
)


class UpstreamTransport:
    def __init__(self, *, config: Any):
        self._config = config

    def forward_json(
        self,
        *,
        endpoint_kind: str,
        payload: Dict[str, Any],
        incoming_headers: Dict[str, str],
        client_name: str,
        client_provider_name: str | None = None,
    ) -> Any:
        return forward_upstream_json(
            config=self._config,
            endpoint_kind=endpoint_kind,
            payload=payload,
            incoming_headers=incoming_headers,
            client_name=client_name,
            client_provider_name=client_provider_name,
        )

    def forward_stream(
        self,
        *,
        endpoint_kind: str,
        payload: Dict[str, Any],
        incoming_headers: Dict[str, str],
        client_name: str,
        client_provider_name: str | None = None,
    ) -> Any:
        return forward_upstream_stream(
            config=self._config,
            endpoint_kind=endpoint_kind,
            payload=payload,
            incoming_headers=incoming_headers,
            client_name=client_name,
            client_provider_name=client_provider_name,
        )

    def forward_models_json(
        self,
        *,
        incoming_headers: Dict[str, str],
        client_name: str,
        client_provider_name: str | None = None,
        query_params: Dict[str, str] | None = None,
    ) -> Any:
        return forward_upstream_models_json(
            config=self._config,
            incoming_headers=incoming_headers,
            client_name=client_name,
            client_provider_name=client_provider_name,
            query_params=query_params,
        )
