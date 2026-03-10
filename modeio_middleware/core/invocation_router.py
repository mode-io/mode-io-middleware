#!/usr/bin/env python3

from __future__ import annotations

from typing import Any, Dict, Iterable

from modeio_middleware.connectors.base import CanonicalInvocation, ConnectorAdapter
from modeio_middleware.core.errors import MiddlewareError


class InvocationRouter:
    def __init__(
        self,
        *,
        connectors: Iterable[ConnectorAdapter],
        default_profile: str,
        upstream_chat_completions_url: str,
        upstream_responses_url: str,
    ):
        self._connectors = tuple(connectors)
        self._default_profile = default_profile
        self._upstream_chat_completions_url = upstream_chat_completions_url
        self._upstream_responses_url = upstream_responses_url

    def parse_http_request(
        self,
        *,
        path: str,
        request_id: str,
        payload: Dict[str, Any],
        incoming_headers: Dict[str, str],
    ) -> CanonicalInvocation:
        connector = self._resolve_connector(path)
        return connector.parse(
            request_id=request_id,
            payload=payload,
            incoming_headers=incoming_headers,
            default_profile=self._default_profile,
            path=path,
        )

    def _resolve_connector(self, path: str) -> ConnectorAdapter:
        for connector in self._connectors:
            if connector.matches(path):
                return connector
        raise MiddlewareError(
            404,
            "MODEIO_ROUTE_NOT_FOUND",
            "route not found",
            retryable=False,
        )

    def build_request_context(self, invocation: CanonicalInvocation) -> Dict[str, Any]:
        return {
            "endpoint_kind": invocation.endpoint_kind,
            "default_profile": self._default_profile,
            "upstream_chat_completions_url": self._upstream_chat_completions_url,
            "upstream_responses_url": self._upstream_responses_url,
            "client_name": invocation.client_name,
            **invocation.connector_context,
        }
