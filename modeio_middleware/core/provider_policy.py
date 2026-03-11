#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_OPENAI_CODEX = "openai-codex"
PROVIDER_MODEIO_MIDDLEWARE = "modeio-middleware"

API_FAMILY_ANTHROPIC_MESSAGES = "anthropic-messages"
API_FAMILY_GOOGLE_GENERATIVE_AI = "google-generative-ai"
API_FAMILY_OPENAI_CODEX_RESPONSES = "openai-codex-responses"
API_FAMILY_OPENAI_COMPLETIONS = "openai-completions"
API_FAMILY_OPENAI_RESPONSES = "openai-responses"

CLIENT_OPENCLAW = "openclaw"
CLIENT_OPENCODE = "opencode"

OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER = "preserve_provider"
OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER = "preserve_provider"
OPENCODE_UNSUPPORTED_OAUTH_PROVIDER_IDS = frozenset({"openai"})

TRANSPORT_ANTHROPIC_MESSAGES = "anthropic_messages"
TRANSPORT_CODEX_NATIVE = "codex_native"
TRANSPORT_GOOGLE_GENERATIVE_AI = "google_generative_ai"
TRANSPORT_OPENAI_COMPAT = "openai_compat"


@dataclass(frozen=True)
class ProviderFamilySpec:
    api_family: str
    transport_kind: str
    openclaw_supported: bool = False
    opencode_supported: bool = False
    openclaw_drop_gateway_v1: bool = False
    user_label: str | None = None


PROVIDER_FAMILY_SPECS = {
    API_FAMILY_OPENAI_COMPLETIONS: ProviderFamilySpec(
        api_family=API_FAMILY_OPENAI_COMPLETIONS,
        transport_kind=TRANSPORT_OPENAI_COMPAT,
        openclaw_supported=True,
        opencode_supported=True,
        user_label="OpenAI-compatible providers",
    ),
    API_FAMILY_OPENAI_RESPONSES: ProviderFamilySpec(
        api_family=API_FAMILY_OPENAI_RESPONSES,
        transport_kind=TRANSPORT_OPENAI_COMPAT,
        user_label="OpenAI responses providers",
    ),
    API_FAMILY_OPENAI_CODEX_RESPONSES: ProviderFamilySpec(
        api_family=API_FAMILY_OPENAI_CODEX_RESPONSES,
        transport_kind=TRANSPORT_CODEX_NATIVE,
        user_label="Codex-native providers",
    ),
    API_FAMILY_ANTHROPIC_MESSAGES: ProviderFamilySpec(
        api_family=API_FAMILY_ANTHROPIC_MESSAGES,
        transport_kind=TRANSPORT_ANTHROPIC_MESSAGES,
        openclaw_supported=True,
        openclaw_drop_gateway_v1=True,
        user_label="Anthropic-compatible providers",
    ),
    API_FAMILY_GOOGLE_GENERATIVE_AI: ProviderFamilySpec(
        api_family=API_FAMILY_GOOGLE_GENERATIVE_AI,
        transport_kind=TRANSPORT_GOOGLE_GENERATIVE_AI,
        user_label="Google Generative AI providers",
    ),
}

OPENCLAW_SUPPORTED_API_FAMILIES = frozenset(
    api_family
    for api_family, spec in PROVIDER_FAMILY_SPECS.items()
    if spec.openclaw_supported
)


def normalize_provider_id(raw_provider_id: str | None) -> str:
    return str(raw_provider_id or "").strip().lower().replace("_", "-")


def normalize_api_family(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text or None


def resolve_provider_family_spec(value: Any) -> ProviderFamilySpec | None:
    api_family = normalize_api_family(value)
    if not api_family:
        return None
    return PROVIDER_FAMILY_SPECS.get(api_family)


def supported_provider_families_for_client(client_name: str | None) -> tuple[str, ...]:
    normalized_client = str(client_name or "").strip().lower().replace("_", "-")
    if normalized_client == CLIENT_OPENCLAW:
        return tuple(
            sorted(
                api_family
                for api_family, spec in PROVIDER_FAMILY_SPECS.items()
                if spec.openclaw_supported
            )
        )
    if normalized_client == CLIENT_OPENCODE:
        return tuple(
            sorted(
                api_family
                for api_family, spec in PROVIDER_FAMILY_SPECS.items()
                if spec.opencode_supported
            )
        )
    return ()


def default_provider_family(provider_id: str | None) -> str:
    normalized_provider = normalize_provider_id(provider_id)
    if normalized_provider == PROVIDER_ANTHROPIC:
        return API_FAMILY_ANTHROPIC_MESSAGES
    if normalized_provider == PROVIDER_OPENAI_CODEX:
        return API_FAMILY_OPENAI_CODEX_RESPONSES
    return API_FAMILY_OPENAI_COMPLETIONS


def transport_kind_for_api_family(api_family: Any) -> str:
    spec = resolve_provider_family_spec(api_family)
    if spec is None:
        return TRANSPORT_OPENAI_COMPAT
    return spec.transport_kind


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
    spec = resolve_provider_family_spec(api_family)
    if spec is not None and spec.openclaw_drop_gateway_v1 and base_url.endswith("/v1"):
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
    api_family: str | None = None
    transport_kind: str | None = None


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
    api_family = API_FAMILY_OPENAI_COMPLETIONS
    family_spec = resolve_provider_family_spec(api_family)
    transport_kind = family_spec.transport_kind if family_spec is not None else None

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
            api_family=api_family,
            transport_kind=transport_kind,
        )

    if not upstream_base_url:
        return OpenCodeRoutePolicy(
            provider_id=provider_id,
            supported=False,
            reason="missing_upstream_base_url",
            upstream_base_url=None,
            auth_type=auth_type,
            api_family=api_family,
            transport_kind=transport_kind,
        )

    return OpenCodeRoutePolicy(
        provider_id=provider_id,
        supported=True,
        reason=None,
        upstream_base_url=upstream_base_url.rstrip("/"),
        auth_type=auth_type,
        api_family=api_family,
        transport_kind=transport_kind,
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
    family_spec = resolve_provider_family_spec(api_family)
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
    if family_spec is None or not family_spec.openclaw_supported:
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
