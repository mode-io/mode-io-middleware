#!/usr/bin/env python3

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Tuple

from modeio_middleware.cli.setup_lib.openclaw_common import (
    OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
    _ensure_config_provider_container,
    _provider_gateway_base_url,
    _preserve_provider_metadata,
    _read_route_metadata,
    _resolve_models_cache_provider_container,
    _string_value,
    _write_route_metadata,
)
from modeio_middleware.core.provider_policy import (
    OpenClawRoutePolicy,
    resolve_openclaw_route_policy,
)


def _policy_to_target(policy: OpenClawRoutePolicy) -> Dict[str, Any]:
    return {
        "supported": policy.supported,
        "reason": policy.reason,
        "providerId": policy.provider_id,
        "providerKey": policy.provider_key,
        "modelId": policy.model_id,
        "primaryRef": policy.primary_ref,
        "restorePrimaryRef": policy.restore_primary_ref,
        "apiFamily": policy.api_family,
        "routeBaseUrl": policy.route_base_url,
        "originalBaseUrl": policy.original_base_url,
        "originalModelsCacheBaseUrl": policy.original_models_cache_base_url,
        "createdConfigProvider": policy.created_config_provider,
        "createdModelsCacheProvider": policy.created_models_cache_provider,
        "configApiPresent": policy.config_api_present,
        "modelsCacheApiPresent": policy.models_cache_api_present,
        "routeMode": policy.route_mode,
    }


def _resolve_preserve_provider_target(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    models_cache_data: Dict[str, Any] | None,
    existing_route_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    policy = resolve_openclaw_route_policy(
        config=config,
        gateway_base_url=gateway_base_url,
        models_cache_data=models_cache_data,
        route_metadata=existing_route_metadata,
    )
    if not policy.supported:
        return _policy_to_target(policy)
    return _policy_to_target(policy)


def _provider_entry_patch(
    provider_obj: Dict[str, Any] | None,
    *,
    route_base_url: str,
    api_family: str,
    api_present: bool,
    create_models: bool,
    model_id: str,
) -> Tuple[Dict[str, Any], bool]:
    updated = copy.deepcopy(provider_obj) if isinstance(provider_obj, dict) else {}
    changed = not isinstance(provider_obj, dict)
    if updated.get("baseUrl") != route_base_url:
        updated["baseUrl"] = route_base_url
        changed = True
    if not api_present and updated.get("api") != api_family:
        updated["api"] = api_family
        changed = True
    if create_models and not isinstance(updated.get("models"), list):
        updated["models"] = [{"id": model_id, "name": model_id}]
        changed = True
    return updated, changed


def _restore_provider_entry(
    provider_obj: Dict[str, Any] | None,
    *,
    route_entry: Dict[str, Any],
    gateway_base_url: str,
    force_remove: bool,
    created_provider_flag: str,
    original_base_field: str,
    api_present_flag: str,
) -> Tuple[Dict[str, Any] | None, bool, bool]:
    if not isinstance(provider_obj, dict):
        return None, False, False
    provider_key = _string_value(route_entry.get("providerKey")) or _string_value(
        route_entry.get("providerId")
    )
    api_family = _string_value(route_entry.get("apiFamily"))
    expected_base_url = (
        _provider_gateway_base_url(
            gateway_base_url,
            provider_key=provider_key,
            api_family=api_family,
        )
        if provider_key and api_family
        else _string_value(route_entry.get("routeBaseUrl"))
    )
    current_base_url = _string_value(provider_obj.get("baseUrl"))
    if (
        not force_remove
        and current_base_url
        and expected_base_url
        and current_base_url.rstrip("/") != expected_base_url.rstrip("/")
    ):
        return provider_obj, False, True

    if bool(route_entry.get(created_provider_flag)):
        return None, True, False

    updated = copy.deepcopy(provider_obj)
    changed = False
    original_base_url = _string_value(route_entry.get(original_base_field))
    if original_base_url:
        if updated.get("baseUrl") != original_base_url:
            updated["baseUrl"] = original_base_url
            changed = True
    elif "baseUrl" in updated:
        del updated["baseUrl"]
        changed = True

    if (
        not bool(route_entry.get(api_present_flag))
        and updated.get("api") == route_entry.get("apiFamily")
    ):
        del updated["api"]
        changed = True
    return updated, changed, False


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
    provider_obj, provider_changed = _provider_entry_patch(
        providers_obj.get(provider_key) if isinstance(providers_obj, dict) else None,
        route_base_url=str(route_target["routeBaseUrl"]),
        api_family=str(route_target["apiFamily"]),
        api_present=bool(route_target["configApiPresent"]),
        create_models=False,
        model_id=str(route_target["modelId"]),
    )
    providers_obj[provider_key] = provider_obj
    models_obj["providers"] = providers_obj
    updated["models"] = models_obj
    changed = changed or provider_changed

    restore_primary_ref = route_target.get("restorePrimaryRef")
    if isinstance(restore_primary_ref, str) and restore_primary_ref:
        agents_obj = updated.get("agents")
        if not isinstance(agents_obj, dict):
            agents_obj = {}
            changed = True
        defaults_obj = agents_obj.get("defaults")
        if not isinstance(defaults_obj, dict):
            defaults_obj = {}
            changed = True
        model_obj = defaults_obj.get("model")
        if not isinstance(model_obj, dict):
            model_obj = {}
            changed = True
        if model_obj.get("primary") != restore_primary_ref:
            model_obj["primary"] = restore_primary_ref
            changed = True
        defaults_obj["model"] = model_obj
        agents_obj["defaults"] = defaults_obj
        updated["agents"] = agents_obj
    return updated, changed


def _apply_preserve_provider_models_cache(
    config: Dict[str, Any],
    route_target: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    updated = copy.deepcopy(config)
    container_obj, providers_obj, provider_parent = _resolve_models_cache_provider_container(
        updated,
        create=True,
    )
    provider_key = str(route_target["providerKey"])
    provider_obj, changed = _provider_entry_patch(
        providers_obj.get(provider_key) if isinstance(providers_obj, dict) else None,
        route_base_url=str(route_target["routeBaseUrl"]),
        api_family=str(route_target["apiFamily"]),
        api_present=bool(route_target["modelsCacheApiPresent"]),
        create_models=bool(route_target["createdModelsCacheProvider"]),
        model_id=str(route_target["modelId"]),
    )
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
        restored, entry_changed, skipped = _restore_provider_entry(
            providers_obj.get(provider_key),
            route_entry=entry,
            gateway_base_url=gateway_base_url,
            force_remove=force_remove,
            created_provider_flag="createdConfigProvider",
            original_base_field="originalBaseUrl",
            api_present_flag="configApiPresent",
        )
        if skipped:
            reasons["skippedProviders"].append(provider_key)
            continue
        if restored is None:
            providers_obj.pop(provider_key, None)
            changed = True
        else:
            providers_obj[provider_key] = restored
            changed = changed or entry_changed
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
        restored, entry_changed, skipped = _restore_provider_entry(
            providers_obj.get(provider_key),
            route_entry=entry,
            gateway_base_url=gateway_base_url,
            force_remove=force_remove,
            created_provider_flag="createdModelsCacheProvider",
            original_base_field="originalModelsCacheBaseUrl",
            api_present_flag="modelsCacheApiPresent",
        )
        if skipped:
            continue
        if restored is None:
            providers_obj.pop(provider_key, None)
            changed = True
            continue
        providers_obj[provider_key] = restored
        changed = changed or entry_changed

    if provider_parent == "models":
        container_obj["providers"] = providers_obj
        updated["models"] = container_obj
    else:
        updated["providers"] = providers_obj
    return updated, changed, "removed" if changed else "provider_base_url_mismatch"
