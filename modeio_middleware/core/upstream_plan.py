#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResolvedCredential:
    provider_id: str
    auth_kind: str
    source: str | None
    guaranteed: bool
    best_effort_reason: str | None = None
    refresh_state: str | None = None


@dataclass(frozen=True)
class ResolvedAuthMaterial:
    authorization: str | None = None
    resolved_headers: dict[str, str] = field(default_factory=dict)
    account_id: str | None = None


@dataclass(frozen=True)
class ResolvedUpstreamPlan:
    provider_id: str
    transport_kind: str
    api_family: str | None = None
    upstream_base_url: str | None = None
    native_base_url: str | None = None
    model_override: str | None = None
    unsupported_family: str | None = None
    supported_families: tuple[str, ...] = ()
    route_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def base_url(self) -> str | None:
        return self.upstream_base_url or self.native_base_url


@dataclass(frozen=True)
class ResolvedClientUpstreamAuth:
    credential: ResolvedCredential
    auth_material: ResolvedAuthMaterial
    upstream_plan: ResolvedUpstreamPlan
    inspection: Any
    explicit_incoming_auth: bool = False
