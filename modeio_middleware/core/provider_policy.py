#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_OPENAI_CODEX = "openai-codex"
PROVIDER_MODEIO_MIDDLEWARE = "modeio-middleware"

OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER = "preserve_provider"
OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER = "preserve_provider"
OPENCODE_UNSUPPORTED_OAUTH_PROVIDER_IDS = frozenset({"openai"})
OPENCLAW_SUPPORTED_API_FAMILIES = frozenset(
    {
        "openai-completions",
        "anthropic-messages",
    }
)


def normalize_provider_id(raw_provider_id: str | None) -> str:
    return str(raw_provider_id or "").strip().lower().replace("_", "-")


def normalize_api_family(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text or None


def is_loopback_base_url(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://127.0.0.1") or text.startswith("http://localhost")


def build_client_gateway_base_url(
    gateway_base_url: str,
    client_name: str,
    *,
    provider_name: str | None = None,
) -> str:
    normalized = str(gateway_base_url).rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    parts = [normalized, "clients", client_name.strip("/")]
    if provider_name:
        parts.append(str(provider_name).strip("/"))
    parts.append("v1")
    return "/".join(part for part in parts if part)


def openclaw_provider_gateway_base_url(
    gateway_base_url: str,
    *,
    provider_key: str,
    api_family: str,
) -> str:
    base_url = build_client_gateway_base_url(
        gateway_base_url,
        "openclaw",
        provider_name=provider_key,
    )
    if api_family == "anthropic-messages" and base_url.endswith("/v1"):
        return base_url[:-3]
    return base_url


def resolve_openclaw_api_family(
    provider_key: str,
    *provider_objects: Any,
) -> str | None:
    del provider_key
    for provider_object in provider_objects:
        if not isinstance(provider_object, Mapping):
            continue
        api_family = normalize_api_family(provider_object.get("api"))
        if api_family:
            return api_family
    return None


def route_metadata_entry(
    route_metadata: Mapping[str, Any] | None,
    provider_id: str,
) -> dict[str, Any]:
    if not isinstance(route_metadata, Mapping):
        return {}
    providers = route_metadata.get("providers")
    normalized_provider = normalize_provider_id(provider_id)
    if not isinstance(providers, Mapping):
        return {}
    for candidate_key, candidate_value in providers.items():
        if normalize_provider_id(candidate_key) != normalized_provider:
            continue
        if isinstance(candidate_value, dict):
            return dict(candidate_value)
    return {}


def mapping_provider_entry(
    providers: Mapping[str, Any] | None,
    provider_key: str,
) -> tuple[str, dict[str, Any] | None]:
    if not isinstance(providers, Mapping):
        return provider_key, None
    provider = providers.get(provider_key)
    if isinstance(provider, dict):
        return provider_key, provider
    normalized_provider = normalize_provider_id(provider_key)
    for candidate_key, candidate_value in providers.items():
        if normalize_provider_id(candidate_key) != normalized_provider:
            continue
        if isinstance(candidate_value, dict):
            return str(candidate_key), candidate_value
    return provider_key, None


def string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def provider_base_url(provider_obj: Mapping[str, Any] | None) -> str | None:
    if not isinstance(provider_obj, Mapping):
        return None
    options_obj = provider_obj.get("options")
    if isinstance(options_obj, Mapping):
        for field_name in ("baseURL", "baseUrl"):
            value = string_value(options_obj.get(field_name))
            if value:
                return value.rstrip("/")
    for field_name in ("baseURL", "baseUrl", "base_url"):
        value = string_value(provider_obj.get(field_name))
        if value:
            return value.rstrip("/")
    return None


@dataclass(frozen=True)
class OpenCodeRoutePolicy:
    provider_id: str | None
    supported: bool
    reason: str | None
    upstream_base_url: str | None
    route_mode: str = OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER
    auth_type: str | None = None


def resolve_opencode_route_policy(
    *,
    config: Mapping[str, Any],
    auth_store: Mapping[str, Any],
    default_upstream_base_url: str | None,
) -> OpenCodeRoutePolicy:
    model_name = config.get("model")
    provider_id = None
    if isinstance(model_name, str) and "/" in model_name:
        prefix, _ = model_name.split("/", 1)
        provider_id = prefix.strip() or None
    if not provider_id:
        return OpenCodeRoutePolicy(
            provider_id=None,
            supported=False,
            reason="missing_active_provider",
            upstream_base_url=None,
        )

    normalized_provider = normalize_provider_id(provider_id)
    provider_root = config.get("provider")
    provider_obj = provider_root.get(provider_id) if isinstance(provider_root, Mapping) else None
    upstream_base_url = provider_base_url(provider_obj)
    if not upstream_base_url or is_loopback_base_url(upstream_base_url):
        upstream_base_url = string_value(default_upstream_base_url)

    auth_entry = auth_store.get(normalized_provider)
    auth_type = None
    if isinstance(auth_entry, Mapping):
        auth_type = string_value(auth_entry.get("type"))

    if (
        normalized_provider in OPENCODE_UNSUPPORTED_OAUTH_PROVIDER_IDS
        and auth_type == "oauth"
    ):
        return OpenCodeRoutePolicy(
            provider_id=provider_id,
            supported=False,
            reason="provider_uses_internal_oauth_transport",
            upstream_base_url=upstream_base_url,
            auth_type=auth_type,
        )

    if not upstream_base_url:
        return OpenCodeRoutePolicy(
            provider_id=provider_id,
            supported=False,
            reason="missing_upstream_base_url",
            upstream_base_url=None,
            auth_type=auth_type,
        )

    return OpenCodeRoutePolicy(
        provider_id=provider_id,
        supported=True,
        reason=None,
        upstream_base_url=upstream_base_url.rstrip("/"),
        auth_type=auth_type,
    )


@dataclass(frozen=True)
class OpenClawRoutePolicy:
    supported: bool
    reason: str | None
    provider_id: str | None
    provider_key: str | None
    model_id: str | None
    primary_ref: str | None
    api_family: str | None
    route_base_url: str | None
    original_base_url: str | None
    original_models_cache_base_url: str | None
    restore_primary_ref: str | None = None
    created_config_provider: bool = False
    created_models_cache_provider: bool = False
    config_api_present: bool = False
    models_cache_api_present: bool = False
    route_mode: str = OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER

    @property
    def upstream_base_url(self) -> str | None:
        return self.original_base_url or self.original_models_cache_base_url


def resolve_openclaw_route_policy(
    *,
    config: Mapping[str, Any],
    gateway_base_url: str,
    models_cache_data: Mapping[str, Any] | None,
    route_metadata: Mapping[str, Any] | None,
    route_provider_id: str | None = None,
) -> OpenClawRoutePolicy:
    current_primary = None
    agents_obj = config.get("agents")
    defaults_obj = agents_obj.get("defaults") if isinstance(agents_obj, Mapping) else None
    model_obj = defaults_obj.get("model") if isinstance(defaults_obj, Mapping) else None
    primary = model_obj.get("primary") if isinstance(model_obj, Mapping) else None
    if isinstance(primary, str) and "/" in primary:
        current_primary = primary
    if not current_primary:
        return OpenClawRoutePolicy(
            supported=False,
            reason="missing_active_provider",
            provider_id=None,
            provider_key=None,
            model_id=None,
            primary_ref=None,
            api_family=None,
            route_base_url=None,
            original_base_url=None,
            original_models_cache_base_url=None,
        )

    provider_key, model_id = current_primary.split("/", 1)
    provider_key = provider_key.strip()
    model_id = model_id.strip()
    normalized_provider_id = normalize_provider_id(route_provider_id or provider_key)

    models_obj = config.get("models")
    config_providers = models_obj.get("providers") if isinstance(models_obj, Mapping) else None
    config_provider_key, config_provider_obj = mapping_provider_entry(config_providers, provider_key)

    models_cache_providers = None
    if isinstance(models_cache_data, Mapping):
        models_obj = models_cache_data.get("models")
        if isinstance(models_obj, Mapping):
            models_cache_providers = models_obj.get("providers")
        if not isinstance(models_cache_providers, Mapping):
            models_cache_providers = models_cache_data.get("providers")
    models_cache_provider_key, models_cache_provider_obj = mapping_provider_entry(
        models_cache_providers,
        provider_key,
    )

    metadata_entry = route_metadata_entry(route_metadata, normalized_provider_id)
    api_family = resolve_openclaw_api_family(
        provider_key,
        config_provider_obj,
        models_cache_provider_obj,
        metadata_entry,
    )
    if not api_family:
        return OpenClawRoutePolicy(
            supported=False,
            reason="missing_api_family",
            provider_id=normalized_provider_id,
            provider_key=provider_key,
            model_id=model_id,
            primary_ref=current_primary,
            api_family=None,
            route_base_url=None,
            original_base_url=None,
            original_models_cache_base_url=None,
        )
    if api_family not in OPENCLAW_SUPPORTED_API_FAMILIES:
        return OpenClawRoutePolicy(
            supported=False,
            reason=f"unsupported_api_family:{api_family}",
            provider_id=normalized_provider_id,
            provider_key=provider_key,
            model_id=model_id,
            primary_ref=current_primary,
            api_family=api_family,
            route_base_url=None,
            original_base_url=None,
            original_models_cache_base_url=None,
        )

    current_config_base_url = provider_base_url(config_provider_obj)
    current_models_cache_base_url = provider_base_url(models_cache_provider_obj)
    original_config_base_url = string_value(metadata_entry.get("originalBaseUrl"))
    if (
        original_config_base_url is None
        and current_config_base_url
        and not is_loopback_base_url(current_config_base_url)
    ):
        original_config_base_url = current_config_base_url

    original_models_cache_base_url = string_value(
        metadata_entry.get("originalModelsCacheBaseUrl")
    )
    if (
        original_models_cache_base_url is None
        and current_models_cache_base_url
        and not is_loopback_base_url(current_models_cache_base_url)
    ):
        original_models_cache_base_url = current_models_cache_base_url

    if original_config_base_url is None and original_models_cache_base_url is None:
        return OpenClawRoutePolicy(
            supported=False,
            reason="missing_upstream_base_url",
            provider_id=normalized_provider_id,
            provider_key=provider_key,
            model_id=model_id,
            primary_ref=current_primary,
            api_family=api_family,
            route_base_url=None,
            original_base_url=None,
            original_models_cache_base_url=None,
        )

    config_api_present = bool(metadata_entry.get("configApiPresent"))
    if not metadata_entry and isinstance(config_provider_obj, Mapping):
        config_api_present = "api" in config_provider_obj
    models_cache_api_present = bool(metadata_entry.get("modelsCacheApiPresent"))
    if not metadata_entry and isinstance(models_cache_provider_obj, Mapping):
        models_cache_api_present = "api" in models_cache_provider_obj

    return OpenClawRoutePolicy(
        supported=True,
        reason=None,
        provider_id=normalized_provider_id,
        provider_key=config_provider_key or provider_key,
        model_id=model_id,
        primary_ref=current_primary,
        api_family=api_family,
        route_base_url=openclaw_provider_gateway_base_url(
            gateway_base_url,
            provider_key=provider_key,
            api_family=api_family,
        ),
        original_base_url=original_config_base_url,
        original_models_cache_base_url=original_models_cache_base_url,
        created_config_provider=not isinstance(config_provider_obj, Mapping),
        created_models_cache_provider=not isinstance(models_cache_provider_obj, Mapping),
        config_api_present=config_api_present,
        models_cache_api_present=models_cache_api_present,
    )
