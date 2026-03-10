#!/usr/bin/env python3

from __future__ import annotations

import copy
from typing import Any, Dict

from modeio_middleware.connectors.base import (
    CanonicalInvocation,
    ConnectorAdapter,
    ConnectorCapabilities,
)
from modeio_middleware.connectors.client_identity import detect_openai_client_name
from modeio_middleware.core.client_auth import normalize_client_upstream_model
from modeio_middleware.core.contracts import (
    ENDPOINT_CHAT_COMPLETIONS,
    ENDPOINT_RESPONSES,
    normalize_modeio_options,
    validate_endpoint_payload,
)
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.profiles import normalize_profile_name

OPENAI_CONNECTOR_PATHS = {
    "/v1/chat/completions": ENDPOINT_CHAT_COMPLETIONS,
    "/v1/responses": ENDPOINT_RESPONSES,
}


def _client_provider_name(incoming_headers: Dict[str, str]) -> str | None:
    for key, value in incoming_headers.items():
        if key.lower() == "x-modeio-client-provider":
            provider_name = str(value).strip()
            if provider_name:
                return provider_name
            return None
    return None
class OpenAIHttpConnector(ConnectorAdapter):
    route_paths = tuple(OPENAI_CONNECTOR_PATHS.keys())

    def parse(
        self,
        *,
        request_id: str,
        payload: Dict[str, Any],
        incoming_headers: Dict[str, str],
        default_profile: str,
        path: str,
    ) -> CanonicalInvocation:
        endpoint_kind = OPENAI_CONNECTOR_PATHS.get(path)
        if endpoint_kind is None:
            raise MiddlewareError(
                404,
                "MODEIO_ROUTE_NOT_FOUND",
                "route not found",
                retryable=False,
            )

        request_body = copy.deepcopy(payload)
        stream_enabled = validate_endpoint_payload(endpoint_kind, request_body)
        options = normalize_modeio_options(
            request_body,
            default_profile=default_profile,
        )
        profile = normalize_profile_name(
            options.profile, default_profile=default_profile
        )
        capabilities = ConnectorCapabilities(can_patch=True, can_block=True)
        client_name = detect_openai_client_name(incoming_headers)
        client_provider_name = _client_provider_name(incoming_headers)
        request_body["model"] = normalize_client_upstream_model(
            request_body.get("model"),
            client_name=client_name,
            client_provider_name=client_provider_name,
        )
        connector_context = {
            "endpoint_kind": endpoint_kind,
            "source": "openai_gateway",
            "client_name": client_name,
            "client_provider_name": client_provider_name,
            "source_event": "http_request",
            "surface_capabilities": capabilities.as_dict(),
        }
        return CanonicalInvocation(
            source="openai_gateway",
            client_name=client_name,
            source_event="http_request",
            endpoint_kind=endpoint_kind,
            phase="request",
            request_id=request_id,
            profile=profile,
            on_plugin_error=options.on_plugin_error,
            plugin_overrides=options.plugin_overrides,
            incoming_headers=dict(incoming_headers),
            request_body=request_body,
            response_body={},
            connector_context=connector_context,
            connector_capabilities=capabilities,
            stream=stream_enabled,
        )
