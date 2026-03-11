#!/usr/bin/env python3

from __future__ import annotations

import copy
from typing import Any, Dict

from modeio_middleware.connectors.base import (
    CanonicalInvocation,
    ConnectorAdapter,
    ConnectorCapabilities,
)
from modeio_middleware.core.request_context import client_route_context_from_headers
from modeio_middleware.core.client_auth import normalize_client_upstream_model
from modeio_middleware.core.contracts import (
    ENDPOINT_ANTHROPIC_MESSAGES,
    normalize_modeio_options,
    validate_endpoint_payload,
)
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.payload_codec import normalize_request_payload
from modeio_middleware.core.profiles import normalize_profile_name

ANTHROPIC_CONNECTOR_PATHS = {
    "/v1/messages": ENDPOINT_ANTHROPIC_MESSAGES,
}
class AnthropicHttpConnector(ConnectorAdapter):
    route_paths = tuple(ANTHROPIC_CONNECTOR_PATHS.keys())

    def parse(
        self,
        *,
        request_id: str,
        payload: Dict[str, Any],
        incoming_headers: Dict[str, str],
        default_profile: str,
        path: str,
    ) -> CanonicalInvocation:
        endpoint_kind = ANTHROPIC_CONNECTOR_PATHS.get(path)
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
            options.profile,
            default_profile=default_profile,
        )
        capabilities = ConnectorCapabilities(can_patch=True, can_block=True)
        route_context = client_route_context_from_headers(
            incoming_headers,
            normalized_path=path,
        )
        request_body["model"] = normalize_client_upstream_model(
            request_body.get("model"),
            client_name=route_context.client_name,
            client_provider_name=route_context.client_provider_name,
        )
        connector_context = {
            "endpoint_kind": endpoint_kind,
            "source": "anthropic_gateway",
            "client_name": route_context.client_name,
            "client_provider_name": route_context.client_provider_name,
            "client_route_context": route_context.as_dict(),
            "source_event": "http_request",
            "surface_capabilities": capabilities.as_dict(),
        }
        normalized_payload = normalize_request_payload(
            endpoint_kind=endpoint_kind,
            source="anthropic_gateway",
            request_body=request_body,
            connector_context=connector_context,
        )
        return CanonicalInvocation(
            source="anthropic_gateway",
            client_name=route_context.client_name,
            source_event="http_request",
            endpoint_kind=endpoint_kind,
            phase="request",
            request_id=request_id,
            profile=profile,
            on_plugin_error=options.on_plugin_error,
            plugin_overrides=options.plugin_overrides,
            incoming_headers=dict(incoming_headers),
            normalized_payload=normalized_payload.to_public_dict(),
            native_payload=normalized_payload.native,
            request_body=request_body,
            response_body={},
            connector_context=connector_context,
            connector_capabilities=capabilities,
            stream=stream_enabled,
        )
