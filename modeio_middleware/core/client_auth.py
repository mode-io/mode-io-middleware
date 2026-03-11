#!/usr/bin/env python3

from __future__ import annotations

from typing import Any, Mapping

from modeio_middleware.connectors.client_identity import (
    CLIENT_CODEX,
    CLIENT_OPENCODE,
    CLIENT_OPENCLAW,
)
from modeio_middleware.core.provider_auth import (
    CredentialInspection,
    CredentialResolver,
    LOCAL_AUTH_PLACEHOLDER,
    resolve_inspection_auth_material,
    resolve_inspection_credential,
    resolve_inspection_upstream_plan,
)
from modeio_middleware.core.request_context import ClientRouteContext
from modeio_middleware.core.upstream_plan import (
    ResolvedAuthMaterial,
    ResolvedCredential,
    ResolvedUpstreamPlan,
)

_RESOLVER = CredentialResolver()


def inspect_codex_native_auth() -> dict[str, Any]:
    return _RESOLVER.inspect(client_name=CLIENT_CODEX).to_public_dict()


def inspect_opencode_native_auth(provider_name: str | None = None) -> dict[str, Any]:
    return _RESOLVER.inspect(
        client_name=CLIENT_OPENCODE,
        provider_name=provider_name,
    ).to_public_dict()


def inspect_openclaw_native_auth(provider_name: str | None = None) -> dict[str, Any]:
    return _RESOLVER.inspect(
        client_name=CLIENT_OPENCLAW,
        provider_name=provider_name,
    ).to_public_dict()


def inspect_client_native_auth(
    *,
    client_name: str,
    client_provider_name: str | None = None,
) -> CredentialInspection:
    return _RESOLVER.inspect(
        client_name=client_name,
        provider_name=client_provider_name,
    )


def resolve_client_route_upstream_plan(
    *,
    route_context: ClientRouteContext,
) -> ResolvedUpstreamPlan:
    return _RESOLVER.resolve_upstream_plan(
        client_name=route_context.client_name,
        provider_name=route_context.client_provider_name,
    )


def resolve_client_inspection_credential(
    inspection: CredentialInspection,
) -> ResolvedCredential:
    return resolve_inspection_credential(inspection)


def resolve_client_inspection_auth_material(
    inspection: CredentialInspection,
) -> ResolvedAuthMaterial:
    return resolve_inspection_auth_material(inspection)


def resolve_client_inspection_upstream_plan(
    inspection: CredentialInspection,
) -> ResolvedUpstreamPlan:
    return resolve_inspection_upstream_plan(inspection)


def resolve_client_upstream_authorization(
    incoming_headers: Mapping[str, str],
    *,
    client_name: str,
    client_provider_name: str | None = None,
) -> str | None:
    return _RESOLVER.resolve_authorization(
        incoming_headers,
        client_name=client_name,
        provider_name=client_provider_name,
    )


def normalize_client_upstream_model(
    model_name: Any,
    *,
    client_name: str,
    client_provider_name: str | None = None,
) -> Any:
    return _RESOLVER.normalize_model_name(
        model_name,
        client_name=client_name,
        provider_name=client_provider_name,
    )


def record_client_native_failure(
    *,
    client_name: str,
    client_provider_name: str | None = None,
    status_code: int,
) -> None:
    inspection = _RESOLVER.inspect(
        client_name=client_name,
        provider_name=client_provider_name,
    )
    _RESOLVER.record_failure(inspection, status_code=status_code)
