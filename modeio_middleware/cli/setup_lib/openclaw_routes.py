#!/usr/bin/env python3

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from modeio_middleware.cli.setup_lib.openclaw_common import (
    OPENCLAW_AUTH_MODE_NATIVE,
    OPENCLAW_AUTH_MODE_MANAGED,
    OPENCLAW_MODEL_ID,
    OPENCLAW_PROVIDER_ID,
    OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
    OPENCLAW_SUPPORTED_API_FAMILIES,
    OPENCLAW_DEFAULT_API_KEY,
    _ensure_config_provider_container,
    _legacy_previous_primary,
    _normalize_api_family,
    _normalize_provider_id,
    _preserve_metadata_entry,
    _preserve_provider_metadata,
    _provider_from_mapping,
    _provider_gateway_base_url,
    _read_route_metadata,
    _resolve_existing_primary,
    _resolve_managed_route_target,
    _resolve_models_cache_provider_container,
    _route_model_ref,
    _string_value,
    _upsert_provider_model,
    _write_route_metadata,
    build_client_gateway_base_url,
    ensure_object,
)


def _resolve_preserve_provider_target(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    models_cache_data: Dict[str, Any] | None,
    existing_route_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    current_primary = _resolve_existing_primary(config)
    primary_ref = current_primary
    restore_primary = None
    if isinstance(primary_ref, str) and primary_ref.startswith(f"{OPENCLAW_PROVIDER_ID}/"):
        previous_primary = _legacy_previous_primary(existing_route_metadata)
        if previous_primary:
            primary_ref = previous_primary
            restore_primary = previous_primary
    if not isinstance(primary_ref, str) or "/" not in primary_ref:
        return {
            "supported": False,
            "reason": "missing_active_provider",
            "currentPrimary": current_primary,
        }

    provider_key, model_id = primary_ref.split("/", 1)
    normalized_provider_id = _normalize_provider_id(provider_key)
    _, models_obj, config_providers = _ensure_config_provider_container(copy.deepcopy(config))
    del models_obj
    config_provider_key, config_provider_obj = _provider_from_mapping(
        config_providers, provider_key
    )
    models_cache_provider_key = provider_key
    models_cache_provider_obj = None
    if isinstance(models_cache_data, dict):
        _, models_cache_providers, _ = _resolve_models_cache_provider_container(
            copy.deepcopy(models_cache_data),
            create=False,
        )
        models_cache_provider_key, models_cache_provider_obj = _provider_from_mapping(
            models_cache_providers, provider_key
        )

    metadata_entry = _preserve_metadata_entry(
        existing_route_metadata,
        normalized_provider_id,
    )
    api_family = _normalize_api_family(
        provider_key,
        config_provider_obj,
        models_cache_provider_obj,
        metadata_entry,
    )
    if not api_family:
        return {
            "supported": False,
            "reason": "missing_api_family",
            "currentPrimary": current_primary,
            "providerId": normalized_provider_id,
            "providerKey": provider_key,
            "modelId": model_id,
            "apiFamily": None,
        }
    if api_family not in OPENCLAW_SUPPORTED_API_FAMILIES:
        return {
            "supported": False,
            "reason": f"unsupported_api_family:{api_family}",
            "currentPrimary": current_primary,
            "providerId": normalized_provider_id,
            "providerKey": provider_key,
            "modelId": model_id,
            "apiFamily": api_family,
        }

    route_base_url = _provider_gateway_base_url(
        gateway_base_url,
        provider_key=provider_key,
        api_family=api_family,
    )
    current_config_base_url = _string_value(
        config_provider_obj.get("baseUrl") if isinstance(config_provider_obj, dict) else None
    )
    current_models_cache_base_url = _string_value(
        models_cache_provider_obj.get("baseUrl")
        if isinstance(models_cache_provider_obj, dict)
        else None
    )

    original_config_base_url = _string_value(metadata_entry.get("originalBaseUrl"))
    if (
        original_config_base_url is None
        and current_config_base_url
        and current_config_base_url.rstrip("/") != route_base_url
    ):
        original_config_base_url = current_config_base_url

    original_models_cache_base_url = _string_value(
        metadata_entry.get("originalModelsCacheBaseUrl")
    )
    if (
        original_models_cache_base_url is None
        and current_models_cache_base_url
        and current_models_cache_base_url.rstrip("/") != route_base_url
    ):
        original_models_cache_base_url = current_models_cache_base_url

    if original_config_base_url is None and original_models_cache_base_url is None:
        return {
            "supported": False,
            "reason": "missing_upstream_base_url",
            "currentPrimary": current_primary,
            "providerId": normalized_provider_id,
            "providerKey": provider_key,
            "modelId": model_id,
            "apiFamily": api_family,
        }

    config_api_present = bool(metadata_entry.get("configApiPresent"))
    if not metadata_entry and isinstance(config_provider_obj, dict):
        config_api_present = "api" in config_provider_obj
    models_cache_api_present = bool(metadata_entry.get("modelsCacheApiPresent"))
    if not metadata_entry and isinstance(models_cache_provider_obj, dict):
        models_cache_api_present = "api" in models_cache_provider_obj

    return {
        "supported": True,
        "reason": None,
        "currentPrimary": current_primary,
        "primaryRef": primary_ref,
        "restorePrimaryRef": restore_primary,
        "providerId": normalized_provider_id,
        "providerKey": provider_key,
        "configProviderKey": config_provider_key,
        "modelsCacheProviderKey": models_cache_provider_key,
        "modelId": model_id,
        "apiFamily": api_family,
        "routeBaseUrl": route_base_url,
        "originalBaseUrl": original_config_base_url,
        "originalModelsCacheBaseUrl": original_models_cache_base_url,
        "createdConfigProvider": not isinstance(config_provider_obj, dict),
        "createdModelsCacheProvider": not isinstance(models_cache_provider_obj, dict),
        "configApiPresent": config_api_present,
        "modelsCacheApiPresent": models_cache_api_present,
        "routeMode": OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
    }


def _cleanup_legacy_managed_route(updated: Dict[str, Any]) -> bool:
    changed = False
    models_obj = updated.get("models")
    if isinstance(models_obj, dict):
        providers_obj = models_obj.get("providers")
        if isinstance(providers_obj, dict) and OPENCLAW_PROVIDER_ID in providers_obj:
            del providers_obj[OPENCLAW_PROVIDER_ID]
            models_obj["providers"] = providers_obj
            updated["models"] = models_obj
            changed = True
    agents_obj = updated.get("agents")
    if isinstance(agents_obj, dict):
        defaults_obj = agents_obj.get("defaults")
        if isinstance(defaults_obj, dict):
            defaults_models_obj = defaults_obj.get("models")
            if isinstance(defaults_models_obj, dict):
                for stale_ref in list(defaults_models_obj.keys()):
                    if stale_ref.startswith(f"{OPENCLAW_PROVIDER_ID}/"):
                        del defaults_models_obj[stale_ref]
                        changed = True
                defaults_obj["models"] = defaults_models_obj
                agents_obj["defaults"] = defaults_obj
                updated["agents"] = agents_obj
    return changed


def _apply_preserve_provider_route(
    config: Dict[str, Any],
    route_target: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    updated = copy.deepcopy(config)
    changed = False
    _, models_obj, providers_obj = _ensure_config_provider_container(updated)
    if models_obj.get("mode") != "merge":
        models_obj["mode"] = "merge"
        changed = True

    provider_key = str(route_target["providerKey"])
    provider_obj = providers_obj.get(provider_key)
    if not isinstance(provider_obj, dict):
        provider_obj = {}
        changed = True

    if provider_obj.get("baseUrl") != route_target["routeBaseUrl"]:
        provider_obj["baseUrl"] = route_target["routeBaseUrl"]
        changed = True

    if not route_target["configApiPresent"] and provider_obj.get("api") != route_target["apiFamily"]:
        provider_obj["api"] = route_target["apiFamily"]
        changed = True

    providers_obj[provider_key] = provider_obj
    models_obj["providers"] = providers_obj
    updated["models"] = models_obj

    restore_primary_ref = route_target.get("restorePrimaryRef")
    if isinstance(restore_primary_ref, str):
        agents_obj = ensure_object(updated.get("agents"), "agents")
        defaults_obj = ensure_object(agents_obj.get("defaults"), "agents.defaults")
        model_obj = ensure_object(defaults_obj.get("model"), "agents.defaults.model")
        if model_obj.get("primary") != restore_primary_ref:
            model_obj["primary"] = restore_primary_ref
            changed = True
        defaults_obj["model"] = model_obj
        agents_obj["defaults"] = defaults_obj
        updated["agents"] = agents_obj
        if _cleanup_legacy_managed_route(updated):
            changed = True

    return updated, changed


def _apply_preserve_provider_models_cache(
    config: Dict[str, Any],
    route_target: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    updated = copy.deepcopy(config)
    changed = False
    container_obj, providers_obj, provider_parent = _resolve_models_cache_provider_container(
        updated,
        create=True,
    )
    provider_key = str(route_target["providerKey"])
    provider_obj = providers_obj.get(provider_key)
    if not isinstance(provider_obj, dict):
        provider_obj = {}
        changed = True

    if provider_obj.get("baseUrl") != route_target["routeBaseUrl"]:
        provider_obj["baseUrl"] = route_target["routeBaseUrl"]
        changed = True

    if (
        not route_target["modelsCacheApiPresent"]
        and provider_obj.get("api") != route_target["apiFamily"]
    ):
        provider_obj["api"] = route_target["apiFamily"]
        changed = True

    if route_target["createdModelsCacheProvider"] and not isinstance(
        provider_obj.get("models"), list
    ):
        provider_obj["models"] = [
            {
                "id": route_target["modelId"],
                "name": route_target["modelId"],
            }
        ]
        changed = True

    providers_obj[provider_key] = provider_obj
    if provider_parent == "models":
        container_obj["providers"] = providers_obj
        updated["models"] = container_obj
    else:
        updated["providers"] = providers_obj
    return updated, changed


def _route_entry_payload(route_target: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "providerId": route_target["providerId"],
        "providerKey": route_target["providerKey"],
        "modelId": route_target["modelId"],
        "primaryRef": route_target["primaryRef"],
        "apiFamily": route_target["apiFamily"],
        "routeMode": OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
        "originalBaseUrl": route_target["originalBaseUrl"],
        "originalModelsCacheBaseUrl": route_target["originalModelsCacheBaseUrl"],
        "createdConfigProvider": bool(route_target["createdConfigProvider"]),
        "createdModelsCacheProvider": bool(route_target["createdModelsCacheProvider"]),
        "configApiPresent": bool(route_target["configApiPresent"]),
        "modelsCacheApiPresent": bool(route_target["modelsCacheApiPresent"]),
        "routeBaseUrl": route_target["routeBaseUrl"],
    }


def _write_preserve_provider_metadata(config_path: Path, route_target: Dict[str, Any]) -> None:
    metadata = _preserve_provider_metadata(_read_route_metadata(config_path))
    providers = metadata["providers"]
    providers[str(route_target["providerId"])] = _route_entry_payload(route_target)
    metadata["providers"] = providers
    _write_route_metadata(config_path, metadata)


def _managed_metadata_mode(route_meta: Dict[str, Any]) -> bool:
    return bool(route_meta) and not isinstance(route_meta.get("providers"), dict)


def _restore_preserve_provider_config(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    force_remove: bool,
    route_meta: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool, Dict[str, Any], str]:
    updated = copy.deepcopy(config)
    changed = False
    reasons: Dict[str, Any] = {"restoredProviders": [], "skippedProviders": []}
    models_obj = updated.get("models")
    providers_obj = models_obj.get("providers") if isinstance(models_obj, dict) else None
    provider_entries = route_meta.get("providers")
    if not isinstance(providers_obj, dict) or not isinstance(provider_entries, dict):
        return updated, False, reasons, "providers_missing"

    remaining_entries = copy.deepcopy(provider_entries)
    for provider_id, entry in provider_entries.items():
        if not isinstance(entry, dict):
            continue
        provider_key = str(entry.get("providerKey") or provider_id)
        current_provider = providers_obj.get(provider_key)
        if not isinstance(current_provider, dict):
            remaining_entries.pop(provider_id, None)
            continue

        expected_base_url = _provider_gateway_base_url(
            gateway_base_url,
            provider_key=provider_key,
            api_family=str(entry.get("apiFamily") or "openai-completions"),
        )
        current_base_url = _string_value(current_provider.get("baseUrl"))
        if (
            not force_remove
            and current_base_url
            and current_base_url.rstrip("/") != expected_base_url
        ):
            reasons["skippedProviders"].append(provider_key)
            continue

        if bool(entry.get("createdConfigProvider")):
            del providers_obj[provider_key]
            changed = True
        else:
            original_base_url = _string_value(entry.get("originalBaseUrl"))
            if original_base_url:
                if current_provider.get("baseUrl") != original_base_url:
                    current_provider["baseUrl"] = original_base_url
                    changed = True
            elif "baseUrl" in current_provider:
                del current_provider["baseUrl"]
                changed = True

            if not bool(entry.get("configApiPresent")) and current_provider.get("api") == entry.get("apiFamily"):
                del current_provider["api"]
                changed = True
            providers_obj[provider_key] = current_provider

        reasons["restoredProviders"].append(provider_key)
        remaining_entries.pop(provider_id, None)

    models_obj["providers"] = providers_obj
    updated["models"] = models_obj
    updated_meta = copy.deepcopy(route_meta)
    updated_meta["providers"] = remaining_entries
    return updated, changed, updated_meta, "removed" if changed else "provider_base_url_mismatch"


def _restore_preserve_provider_models_cache(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    force_remove: bool,
    route_meta: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool, str]:
    updated = copy.deepcopy(config)
    changed = False
    provider_entries = route_meta.get("providers")
    if not isinstance(provider_entries, dict):
        return updated, False, "providers_missing"

    container_obj, providers_obj, provider_parent = _resolve_models_cache_provider_container(
        updated,
        create=False,
    )
    if not isinstance(providers_obj, dict):
        return updated, False, "providers_missing"

    for provider_id, entry in provider_entries.items():
        if not isinstance(entry, dict):
            continue
        provider_key = str(entry.get("providerKey") or provider_id)
        current_provider = providers_obj.get(provider_key)
        if not isinstance(current_provider, dict):
            continue
        expected_base_url = _provider_gateway_base_url(
            gateway_base_url,
            provider_key=provider_key,
            api_family=str(entry.get("apiFamily") or "openai-completions"),
        )
        current_base_url = _string_value(current_provider.get("baseUrl"))
        if (
            not force_remove
            and current_base_url
            and current_base_url.rstrip("/") != expected_base_url
        ):
            continue

        if bool(entry.get("createdModelsCacheProvider")):
            del providers_obj[provider_key]
            changed = True
            continue

        original_base_url = _string_value(entry.get("originalModelsCacheBaseUrl"))
        if original_base_url:
            if current_provider.get("baseUrl") != original_base_url:
                current_provider["baseUrl"] = original_base_url
                changed = True
        elif "baseUrl" in current_provider:
            del current_provider["baseUrl"]
            changed = True

        if (
            not bool(entry.get("modelsCacheApiPresent"))
            and current_provider.get("api") == entry.get("apiFamily")
        ):
            del current_provider["api"]
            changed = True
        providers_obj[provider_key] = current_provider

    if provider_parent == "models":
        container_obj["providers"] = providers_obj
        updated["models"] = container_obj
    else:
        updated["providers"] = providers_obj
    return updated, changed, "removed" if changed else "provider_base_url_mismatch"


def _apply_managed_provider_route(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    auth_mode: str,
    existing_route_metadata: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], bool]:
    updated = copy.deepcopy(config)
    changed = False
    target = _resolve_managed_route_target(
        updated,
        auth_mode,
        existing_route_metadata=existing_route_metadata,
    )
    normalized = build_client_gateway_base_url(
        gateway_base_url,
        "openclaw",
        provider_name=target["nativeProvider"]
        if target["authMode"] == OPENCLAW_AUTH_MODE_NATIVE
        else None,
    )
    route_model_ref = _route_model_ref(target["routeModelId"])

    models_obj = ensure_object(updated.get("models"), "models")
    if models_obj.get("mode") != "merge":
        models_obj["mode"] = "merge"
        changed = True

    providers_obj = ensure_object(models_obj.get("providers"), "models.providers")
    provider_obj = ensure_object(
        providers_obj.get(OPENCLAW_PROVIDER_ID),
        f"models.providers.{OPENCLAW_PROVIDER_ID}",
    )

    if provider_obj.get("baseUrl") != normalized:
        provider_obj["baseUrl"] = normalized
        changed = True

    if provider_obj.get("api") != "openai-completions":
        provider_obj["api"] = "openai-completions"
        changed = True

    if provider_obj.get("authHeader") is not False:
        provider_obj["authHeader"] = False
        changed = True

    current_api_key = provider_obj.get("apiKey")
    if not isinstance(current_api_key, str) or not current_api_key.strip():
        if current_api_key != OPENCLAW_DEFAULT_API_KEY:
            changed = True
        provider_obj["apiKey"] = OPENCLAW_DEFAULT_API_KEY

    provider_models, models_changed = _upsert_provider_model(
        provider_obj.get("models"), target["routeModelId"]
    )
    if models_changed:
        changed = True
    provider_obj["models"] = provider_models

    providers_obj[OPENCLAW_PROVIDER_ID] = provider_obj
    models_obj["providers"] = providers_obj
    updated["models"] = models_obj

    agents_obj = ensure_object(updated.get("agents"), "agents")
    defaults_obj = ensure_object(agents_obj.get("defaults"), "agents.defaults")

    model_obj = ensure_object(defaults_obj.get("model"), "agents.defaults.model")
    if model_obj.get("primary") != route_model_ref:
        model_obj["primary"] = route_model_ref
        changed = True
    defaults_obj["model"] = model_obj

    defaults_models_obj = ensure_object(defaults_obj.get("models"), "agents.defaults.models")
    route_obj = ensure_object(
        defaults_models_obj.get(route_model_ref),
        f"agents.defaults.models.{route_model_ref}",
    )
    params_obj = ensure_object(
        route_obj.get("params"),
        f"agents.defaults.models.{route_model_ref}.params",
    )
    if params_obj.get("transport") != "sse":
        params_obj["transport"] = "sse"
        changed = True
    route_obj["params"] = params_obj
    defaults_models_obj[route_model_ref] = route_obj
    for stale_ref in list(defaults_models_obj.keys()):
        if stale_ref.startswith(f"{OPENCLAW_PROVIDER_ID}/") and stale_ref != route_model_ref:
            del defaults_models_obj[stale_ref]
            changed = True
    defaults_obj["models"] = defaults_models_obj

    agents_obj["defaults"] = defaults_obj
    updated["agents"] = agents_obj

    return updated, changed


def _remove_managed_provider_route(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    force_remove: bool,
    auth_mode: str,
    native_provider: str | None,
    route_model_id: str,
    previous_primary: str | None,
) -> Tuple[Dict[str, Any], bool, Optional[str], str]:
    updated = copy.deepcopy(config)

    models_obj = updated.get("models")
    if not isinstance(models_obj, dict):
        return updated, False, None, "models_missing"

    providers_obj = models_obj.get("providers")
    if not isinstance(providers_obj, dict):
        return updated, False, None, "providers_missing"

    provider_obj = providers_obj.get(OPENCLAW_PROVIDER_ID)
    if not isinstance(provider_obj, dict):
        return updated, False, None, "provider_missing"

    expected_base_url = build_client_gateway_base_url(
        gateway_base_url,
        "openclaw",
        provider_name=native_provider if auth_mode == OPENCLAW_AUTH_MODE_NATIVE else None,
    )

    raw_base_url = provider_obj.get("baseUrl")
    removed_base_url = raw_base_url if isinstance(raw_base_url, str) else None

    if not force_remove:
        if not isinstance(raw_base_url, str) or not raw_base_url.strip():
            return updated, False, None, "provider_base_url_not_set"

        normalized_current = raw_base_url.rstrip("/")
        if normalized_current != expected_base_url:
            return updated, False, raw_base_url, "provider_base_url_mismatch"

    del providers_obj[OPENCLAW_PROVIDER_ID]
    models_obj["providers"] = providers_obj
    updated["models"] = models_obj

    agents_obj = updated.get("agents")
    if isinstance(agents_obj, dict):
        defaults_obj = agents_obj.get("defaults")
        if isinstance(defaults_obj, dict):
            model_obj = defaults_obj.get("model")
            route_model_ref = _route_model_ref(route_model_id)
            if isinstance(model_obj, dict) and model_obj.get("primary") == route_model_ref:
                if previous_primary:
                    model_obj["primary"] = previous_primary
                else:
                    del model_obj["primary"]

            defaults_models_obj = defaults_obj.get("models")
            if isinstance(defaults_models_obj, dict):
                defaults_models_obj.pop(route_model_ref, None)

    return updated, True, removed_base_url, "removed"


def _apply_managed_models_cache_provider(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    auth_mode: str,
    native_provider: str | None,
    route_model_id: str,
) -> Tuple[Dict[str, Any], bool]:
    updated = copy.deepcopy(config)
    changed = False
    normalized = build_client_gateway_base_url(
        gateway_base_url,
        "openclaw",
        provider_name=native_provider if auth_mode == OPENCLAW_AUTH_MODE_NATIVE else None,
    )

    container_obj, providers_obj, provider_parent = _resolve_models_cache_provider_container(
        updated,
        create=True,
    )

    provider_obj = ensure_object(
        providers_obj.get(OPENCLAW_PROVIDER_ID),
        (
            f"models.providers.{OPENCLAW_PROVIDER_ID}"
            if provider_parent == "models"
            else f"providers.{OPENCLAW_PROVIDER_ID}"
        ),
    )

    if provider_obj.get("baseUrl") != normalized:
        provider_obj["baseUrl"] = normalized
        changed = True

    if provider_obj.get("api") != "openai-completions":
        provider_obj["api"] = "openai-completions"
        changed = True

    if provider_obj.get("authHeader") is not False:
        provider_obj["authHeader"] = False
        changed = True

    current_api_key = provider_obj.get("apiKey")
    if not isinstance(current_api_key, str) or not current_api_key.strip():
        if current_api_key != OPENCLAW_DEFAULT_API_KEY:
            changed = True
        provider_obj["apiKey"] = OPENCLAW_DEFAULT_API_KEY

    provider_models, models_changed = _upsert_provider_model(
        provider_obj.get("models"), route_model_id
    )
    if models_changed:
        changed = True
    provider_obj["models"] = provider_models

    providers_obj[OPENCLAW_PROVIDER_ID] = provider_obj
    if provider_parent == "models":
        container_obj["providers"] = providers_obj
        updated["models"] = container_obj
    else:
        updated["providers"] = providers_obj
    return updated, changed


def _remove_managed_models_cache_provider(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    force_remove: bool,
    auth_mode: str,
    native_provider: str | None,
) -> Tuple[Dict[str, Any], bool, Optional[str], str]:
    updated = copy.deepcopy(config)

    container_obj, providers_obj, provider_parent = _resolve_models_cache_provider_container(
        updated,
        create=False,
    )
    if not isinstance(providers_obj, dict):
        return updated, False, None, "providers_missing"

    provider_obj = providers_obj.get(OPENCLAW_PROVIDER_ID)
    if not isinstance(provider_obj, dict):
        return updated, False, None, "provider_missing"

    raw_base_url = provider_obj.get("baseUrl")
    removed_base_url = raw_base_url if isinstance(raw_base_url, str) else None

    if not force_remove:
        if not isinstance(raw_base_url, str) or not raw_base_url.strip():
            return updated, False, None, "provider_base_url_not_set"

        normalized_target = build_client_gateway_base_url(
            gateway_base_url,
            "openclaw",
            provider_name=native_provider if auth_mode == OPENCLAW_AUTH_MODE_NATIVE else None,
        )
        normalized_current = raw_base_url.rstrip("/")
        if normalized_current != normalized_target:
            return updated, False, raw_base_url, "provider_base_url_mismatch"

    del providers_obj[OPENCLAW_PROVIDER_ID]
    if provider_parent == "models":
        container_obj["providers"] = providers_obj
        updated["models"] = container_obj
    else:
        updated["providers"] = providers_obj
    return updated, True, removed_base_url, "removed"
