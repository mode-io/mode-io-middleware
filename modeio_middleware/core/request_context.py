#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from modeio_middleware.connectors.client_identity import (
    CLIENT_UNKNOWN,
    detect_openai_client_name,
)

CLIENT_HEADER_NAME = "x-modeio-client"
CLIENT_PROVIDER_HEADER_NAME = "x-modeio-client-provider"


def _header(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return str(value)
    return ""


def client_provider_name_from_headers(headers: Mapping[str, str]) -> str | None:
    provider_name = _header(headers, CLIENT_PROVIDER_HEADER_NAME).strip()
    return provider_name or None
@dataclass(frozen=True)
class ClientRouteContext:
    client_name: str = CLIENT_UNKNOWN
    client_provider_name: str | None = None
    normalized_path: str | None = None
    is_client_scoped: bool = False

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "client_name": self.client_name,
            "client_provider_name": self.client_provider_name,
            "normalized_path": self.normalized_path,
            "is_client_scoped": self.is_client_scoped,
        }


def client_route_context_from_headers(
    headers: Mapping[str, str],
    *,
    normalized_path: str | None = None,
) -> ClientRouteContext:
    client_name = detect_openai_client_name(headers)
    client_provider_name = client_provider_name_from_headers(headers)
    is_client_scoped = bool(_header(headers, CLIENT_HEADER_NAME).strip() or client_provider_name)
    return ClientRouteContext(
        client_name=client_name,
        client_provider_name=client_provider_name,
        normalized_path=normalized_path,
        is_client_scoped=is_client_scoped,
    )


def client_route_context_from_mapping(value: Mapping[str, Any] | None) -> ClientRouteContext | None:
    if not isinstance(value, Mapping):
        return None
    client_name = str(value.get("client_name") or "").strip() or CLIENT_UNKNOWN
    provider_name = str(value.get("client_provider_name") or "").strip() or None
    normalized_path = str(value.get("normalized_path") or "").strip() or None
    return ClientRouteContext(
        client_name=client_name,
        client_provider_name=provider_name,
        normalized_path=normalized_path,
        is_client_scoped=bool(value.get("is_client_scoped")),
    )
