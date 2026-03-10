#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from modeio_middleware.cli.setup_lib.common import (
    build_client_gateway_base_url,
    SetupError,
    detect_os_name,
    ensure_object,
    read_json_file,
    utc_timestamp,
    write_json_file,
)

OPENCLAW_PROVIDER_ID = "modeio-middleware"
OPENCLAW_MODEL_ID = "middleware-default"
OPENCLAW_MODEL_REF = f"{OPENCLAW_PROVIDER_ID}/{OPENCLAW_MODEL_ID}"
OPENCLAW_MODEL_NAME = "Modeio Middleware Default"
OPENCLAW_DEFAULT_API_KEY = "modeio-middleware"
OPENCLAW_AUTH_MODE_NATIVE = "native"
OPENCLAW_AUTH_MODE_MANAGED = "managed"
OPENCLAW_DEFAULT_STATE_DIRNAME = ".openclaw"
OPENCLAW_CONFIG_FILENAMES = {
    "openclaw.json",
    "clawdbot.json",
    "moltbot.json",
    "moldbot.json",
}
OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER = "preserve_provider"
OPENCLAW_SUPPORTED_API_FAMILIES = {
    "openai-completions",
    "anthropic-messages",
}


def _route_metadata_path(config_path: Path) -> Path:
    return config_path.with_name(f"{config_path.name}.modeio-route.json")


def _write_route_metadata(config_path: Path, payload: Dict[str, Any]) -> None:
    _route_metadata_path(config_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_route_metadata(config_path: Path) -> Dict[str, Any]:
    sidecar_path = _route_metadata_path(config_path)
    if not sidecar_path.exists():
        return {}
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _remove_route_metadata(config_path: Path) -> None:
    sidecar_path = _route_metadata_path(config_path)
    if sidecar_path.exists() or sidecar_path.is_symlink():
        sidecar_path.unlink()


def _route_model_ref(model_id: str) -> str:
    return f"{OPENCLAW_PROVIDER_ID}/{model_id}"


def _model_name(model_id: str) -> str:
    if model_id == OPENCLAW_MODEL_ID:
        return OPENCLAW_MODEL_NAME
    return f"Modeio Middleware {model_id}"


def _upsert_provider_model(models_value: Any, model_id: str) -> Tuple[Sequence[Any], bool]:
    default_model = {
        "id": model_id,
        "name": _model_name(model_id),
    }
    if not isinstance(models_value, list):
        return [default_model], True

    updated_models = copy.deepcopy(models_value)
    for index, model in enumerate(updated_models):
        if not isinstance(model, dict):
            continue
        if model.get("id") != model_id:
            continue

        changed = False
        if model.get("name") != default_model["name"]:
            model["name"] = default_model["name"]
            changed = True
        updated_models[index] = model
        return updated_models, changed

    updated_models.append(default_model)
    return updated_models, True


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text else None


def _normalize_provider_id(raw_provider_id: str | None) -> str:
    return str(raw_provider_id or "").strip().lower().replace("_", "-")


def _normalize_anthropic_base_url(base_url: str) -> str:
    text = base_url.rstrip("/")
    if text.endswith("/v1"):
        return text[:-3]
    return text


def _provider_gateway_base_url(
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
    if api_family == "anthropic-messages":
        return _normalize_anthropic_base_url(base_url)
    return base_url


def _resolve_existing_primary(config: Dict[str, Any]) -> str | None:
    agents_obj = config.get("agents")
    if not isinstance(agents_obj, dict):
        return None
    defaults_obj = agents_obj.get("defaults")
    if not isinstance(defaults_obj, dict):
        return None
    model_obj = defaults_obj.get("model")
    if not isinstance(model_obj, dict):
        return None
    primary = model_obj.get("primary")
    if not isinstance(primary, str) or "/" not in primary:
        return None
    return primary


def _resolve_managed_route_target(
    config: Dict[str, Any],
    auth_mode: str,
    existing_route_metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    previous_primary = _resolve_existing_primary(config)
    actual_mode = auth_mode
    native_provider = None
    native_model = None
    route_model = OPENCLAW_MODEL_ID

    if auth_mode == OPENCLAW_AUTH_MODE_NATIVE and previous_primary:
        provider_name, model_id = previous_primary.split("/", 1)
        if provider_name != OPENCLAW_PROVIDER_ID:
            native_provider = provider_name
            native_model = model_id
            route_model = model_id
    if (
        auth_mode == OPENCLAW_AUTH_MODE_NATIVE
        and not native_provider
        and isinstance(existing_route_metadata, dict)
    ):
        metadata_provider = existing_route_metadata.get("nativeProvider")
        metadata_model = existing_route_metadata.get("nativeModelId")
        metadata_previous = existing_route_metadata.get("previousPrimary")
        if isinstance(metadata_provider, str) and metadata_provider.strip():
            native_provider = metadata_provider
            if isinstance(metadata_model, str) and metadata_model.strip():
                native_model = metadata_model
                route_model = metadata_model
            if isinstance(metadata_previous, str) and metadata_previous.strip():
                previous_primary = metadata_previous
    if auth_mode == OPENCLAW_AUTH_MODE_NATIVE and not native_provider:
        actual_mode = OPENCLAW_AUTH_MODE_MANAGED

    return {
        "authMode": actual_mode,
        "previousPrimary": previous_primary,
        "nativeProvider": native_provider,
        "nativeModelId": native_model,
        "routeModelId": route_model,
    }


def default_openclaw_config_path(
    *,
    os_name: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    resolved_env = env or os.environ
    override = resolved_env.get("OPENCLAW_CONFIG_PATH", "").strip()
    if override:
        return Path(override).expanduser()

    resolved_home = home or Path.home()
    system_name = detect_os_name(os_name)
    if system_name == "windows":
        app_data = resolved_env.get("APPDATA", "").strip()
        if app_data:
            return Path(app_data) / "openclaw" / "openclaw.json"
        return resolved_home / "AppData" / "Roaming" / "openclaw" / "openclaw.json"

    return resolved_home / ".openclaw" / "openclaw.json"


def default_openclaw_models_cache_path(
    *,
    config_path: Path,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    resolved_env = env or os.environ

    raw_agent_dir = (
        resolved_env.get("OPENCLAW_AGENT_DIR", "").strip()
        or resolved_env.get("PI_CODING_AGENT_DIR", "").strip()
    )
    if raw_agent_dir:
        return Path(raw_agent_dir).expanduser() / "models.json"

    raw_state_dir = (
        resolved_env.get("OPENCLAW_STATE_DIR", "").strip()
        or resolved_env.get("CLAWDBOT_STATE_DIR", "").strip()
    )
    if raw_state_dir:
        return Path(raw_state_dir).expanduser() / "agents" / "main" / "agent" / "models.json"

    if config_path.name.strip().lower() in OPENCLAW_CONFIG_FILENAMES:
        return config_path.parent / "agents" / "main" / "agent" / "models.json"

    resolved_home = home or Path.home()
    return resolved_home / OPENCLAW_DEFAULT_STATE_DIRNAME / "agents" / "main" / "agent" / "models.json"


def _ensure_config_provider_container(
    config: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    models_obj = ensure_object(config.get("models"), "models")
    providers_obj = ensure_object(models_obj.get("providers"), "models.providers")
    return config, models_obj, providers_obj


def _resolve_models_cache_provider_container(
    config: Dict[str, Any],
    *,
    create: bool,
) -> tuple[Dict[str, Any], Dict[str, Any], str]:
    models_obj = config.get("models")
    root_providers_obj = config.get("providers")
    if isinstance(models_obj, dict):
        normalized_models = ensure_object(models_obj, "models")
        providers_obj = ensure_object(normalized_models.get("providers"), "models.providers")
        return normalized_models, providers_obj, "models"
    if isinstance(root_providers_obj, dict):
        providers_obj = ensure_object(root_providers_obj, "providers")
        return config, providers_obj, "root"
    if not create:
        return config, {}, "root"
    normalized_models = ensure_object(models_obj, "models")
    providers_obj = ensure_object(normalized_models.get("providers"), "models.providers")
    return normalized_models, providers_obj, "models"


def _provider_from_mapping(
    mapping: Dict[str, Any],
    provider_key: str,
) -> tuple[str, Dict[str, Any] | None]:
    provider = mapping.get(provider_key)
    if isinstance(provider, dict):
        return provider_key, provider
    normalized_provider = _normalize_provider_id(provider_key)
    for candidate_key, candidate_value in mapping.items():
        if _normalize_provider_id(candidate_key) != normalized_provider:
            continue
        if isinstance(candidate_value, dict):
            return str(candidate_key), candidate_value
    return provider_key, None


def _legacy_previous_primary(existing_route_metadata: Dict[str, Any]) -> str | None:
    previous_primary = existing_route_metadata.get("previousPrimary")
    if isinstance(previous_primary, str) and "/" in previous_primary:
        return previous_primary
    return None


def _normalize_api_family(provider_key: str, *provider_objects: Any) -> str:
    for provider_object in provider_objects:
        if not isinstance(provider_object, dict):
            continue
        api_family = _string_value(provider_object.get("api"))
        if api_family:
            return api_family.lower()
    normalized_provider = _normalize_provider_id(provider_key)
    if normalized_provider == "anthropic":
        return "anthropic-messages"
    if normalized_provider == "openai-codex":
        return "openai-codex-responses"
    return "openai-completions"


def _preserve_provider_metadata(existing_route_metadata: Dict[str, Any]) -> Dict[str, Any]:
    providers = existing_route_metadata.get("providers")
    if (
        existing_route_metadata.get("routeMode") == OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER
        and isinstance(providers, dict)
    ):
        return {
            "routeMode": OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
            "providers": copy.deepcopy(providers),
        }
    return {
        "routeMode": OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
        "providers": {},
    }


def _preserve_metadata_entry(
    existing_route_metadata: Dict[str, Any],
    provider_id: str,
) -> Dict[str, Any]:
    providers = existing_route_metadata.get("providers")
    if not isinstance(providers, dict):
        return {}
    entry = providers.get(provider_id)
    return copy.deepcopy(entry) if isinstance(entry, dict) else {}


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


def apply_openclaw_provider_route(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    auth_mode: str,
    existing_route_metadata: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], bool]:
    route_metadata = existing_route_metadata or {}
    if auth_mode == OPENCLAW_AUTH_MODE_MANAGED:
        return _apply_managed_provider_route(
            config,
            gateway_base_url,
            auth_mode=auth_mode,
            existing_route_metadata=route_metadata,
        )

    route_target = _resolve_preserve_provider_target(
        config,
        gateway_base_url,
        models_cache_data=None,
        existing_route_metadata=route_metadata,
    )
    if not route_target.get("supported"):
        return copy.deepcopy(config), False
    return _apply_preserve_provider_route(config, route_target)


def remove_openclaw_provider_route(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    force_remove: bool,
    auth_mode: str,
    native_provider: str | None,
    route_model_id: str,
    previous_primary: str | None,
) -> Tuple[Dict[str, Any], bool, Optional[str], str]:
    return _remove_managed_provider_route(
        config,
        gateway_base_url,
        force_remove=force_remove,
        auth_mode=auth_mode,
        native_provider=native_provider,
        route_model_id=route_model_id,
        previous_primary=previous_primary,
    )


def apply_openclaw_config_file(
    *,
    config_path: Path,
    gateway_base_url: str,
    create_if_missing: bool,
    auth_mode: str,
    models_cache_path: Path | None = None,
) -> Dict[str, Any]:
    existed = config_path.exists()
    if not existed and not create_if_missing:
        raise SetupError(
            f"OpenClaw config not found: {config_path}. Use --create-openclaw-config to create it."
        )

    config_data: Dict[str, Any] = {}
    if existed:
        config_data = read_json_file(config_path)
    models_cache_data: Dict[str, Any] | None = None
    if models_cache_path is not None and models_cache_path.exists():
        models_cache_data = read_json_file(models_cache_path)
    existing_route_metadata = _read_route_metadata(config_path)

    if auth_mode == OPENCLAW_AUTH_MODE_MANAGED:
        route_target = _resolve_managed_route_target(
            config_data,
            auth_mode,
            existing_route_metadata=existing_route_metadata,
        )
        updated, changed = _apply_managed_provider_route(
            config_data,
            gateway_base_url,
            auth_mode=auth_mode,
            existing_route_metadata=existing_route_metadata,
        )
        backup_path = None
        if changed:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            if existed:
                backup_path = config_path.with_name(f"{config_path.name}.bak.{utc_timestamp()}")
                shutil.copy2(config_path, backup_path)
            write_json_file(config_path, updated)
            _write_route_metadata(
                config_path,
                {
                    **route_target,
                    "baseUrl": build_client_gateway_base_url(
                        gateway_base_url,
                        "openclaw",
                        provider_name=route_target["nativeProvider"]
                        if route_target["authMode"] == OPENCLAW_AUTH_MODE_NATIVE
                        else None,
                    ),
                },
            )
        return {
            "path": str(config_path),
            "changed": changed,
            "created": (not existed) and changed,
            "backupPath": str(backup_path) if backup_path else None,
            "authMode": route_target["authMode"],
            "nativeProvider": route_target["nativeProvider"],
            "routeModelId": route_target["routeModelId"],
            "routeMode": "managed_provider",
        }

    route_target = _resolve_preserve_provider_target(
        config_data,
        gateway_base_url,
        models_cache_data=models_cache_data,
        existing_route_metadata=existing_route_metadata,
    )
    if not route_target.get("supported"):
        if not existed and create_if_missing:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_file(config_path, {})
        return {
            "path": str(config_path),
            "changed": False,
            "created": (not existed) and create_if_missing,
            "backupPath": None,
            "authMode": OPENCLAW_AUTH_MODE_NATIVE,
            "providerId": route_target.get("providerId"),
            "providerKey": route_target.get("providerKey"),
            "modelId": route_target.get("modelId"),
            "apiFamily": route_target.get("apiFamily"),
            "routeMode": OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
            "supported": False,
            "reason": route_target.get("reason"),
        }

    updated, changed = _apply_preserve_provider_route(config_data, route_target)
    backup_path = None
    if changed:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            backup_path = config_path.with_name(f"{config_path.name}.bak.{utc_timestamp()}")
            shutil.copy2(config_path, backup_path)
        write_json_file(config_path, updated)
    _write_preserve_provider_metadata(config_path, route_target)

    return {
        "path": str(config_path),
        "changed": changed,
        "created": (not existed) and changed,
        "backupPath": str(backup_path) if backup_path else None,
        "authMode": OPENCLAW_AUTH_MODE_NATIVE,
        "providerId": route_target["providerId"],
        "providerKey": route_target["providerKey"],
        "modelId": route_target["modelId"],
        "apiFamily": route_target["apiFamily"],
        "routeBaseUrl": route_target["routeBaseUrl"],
        "routeMode": OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
        "supported": True,
    }


def uninstall_openclaw_config_file(
    *,
    config_path: Path,
    gateway_base_url: str,
    force_remove: bool,
) -> Dict[str, Any]:
    if not config_path.exists():
        return {
            "path": str(config_path),
            "changed": False,
            "backupPath": None,
            "reason": "config_not_found",
            "removedBaseUrl": None,
        }

    config_data = read_json_file(config_path)
    route_meta = _read_route_metadata(config_path)
    if _managed_metadata_mode(route_meta):
        auth_mode = str(route_meta.get("authMode") or OPENCLAW_AUTH_MODE_MANAGED)
        native_provider = route_meta.get("nativeProvider")
        route_model_id = str(route_meta.get("routeModelId") or OPENCLAW_MODEL_ID)
        previous_primary = route_meta.get("previousPrimary")
        updated, changed, removed_value, reason = _remove_managed_provider_route(
            config_data,
            gateway_base_url,
            force_remove=force_remove,
            auth_mode=auth_mode,
            native_provider=(
                str(native_provider) if isinstance(native_provider, str) else None
            ),
            route_model_id=route_model_id,
            previous_primary=(
                str(previous_primary) if isinstance(previous_primary, str) else None
            ),
        )

        backup_path = None
        if changed:
            backup_path = config_path.with_name(f"{config_path.name}.bak.{utc_timestamp()}")
            shutil.copy2(config_path, backup_path)
            write_json_file(config_path, updated)
            _remove_route_metadata(config_path)

        return {
            "path": str(config_path),
            "changed": changed,
            "backupPath": str(backup_path) if backup_path else None,
            "reason": reason,
            "removedBaseUrl": removed_value,
            "authMode": auth_mode,
            "nativeProvider": (
                str(native_provider) if isinstance(native_provider, str) else None
            ),
            "routeMode": "managed_provider",
        }

    updated, changed, updated_meta, reason = _restore_preserve_provider_config(
        config_data,
        gateway_base_url,
        force_remove=force_remove,
        route_meta=route_meta,
    )

    backup_path = None
    if changed:
        backup_path = config_path.with_name(f"{config_path.name}.bak.{utc_timestamp()}")
        shutil.copy2(config_path, backup_path)
        write_json_file(config_path, updated)
        if updated_meta.get("providers"):
            _write_route_metadata(config_path, updated_meta)
        else:
            _remove_route_metadata(config_path)

    return {
        "path": str(config_path),
        "changed": changed,
        "backupPath": str(backup_path) if backup_path else None,
        "reason": reason,
        "routeMode": OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
        "restoredProviders": updated_meta.get("providers", {}),
    }


def apply_openclaw_models_cache_file(
    *,
    models_cache_path: Path,
    gateway_base_url: str,
    config_path: Path,
    auth_mode: str | None = None,
    native_provider: str | None = None,
    route_model_id: str | None = None,
) -> Dict[str, Any]:
    del native_provider
    existed = models_cache_path.exists()

    config_data: Dict[str, Any] = {}
    if existed:
        config_data = read_json_file(models_cache_path)

    route_meta = _read_route_metadata(config_path)
    if _managed_metadata_mode(route_meta) or auth_mode == OPENCLAW_AUTH_MODE_MANAGED:
        resolved_auth_mode = str(route_meta.get("authMode") or auth_mode or OPENCLAW_AUTH_MODE_MANAGED)
        resolved_native_provider = route_meta.get("nativeProvider")
        resolved_route_model_id = str(route_meta.get("routeModelId") or route_model_id or OPENCLAW_MODEL_ID)
        updated, changed = _apply_managed_models_cache_provider(
            config_data,
            gateway_base_url,
            auth_mode=resolved_auth_mode,
            native_provider=(
                str(resolved_native_provider)
                if isinstance(resolved_native_provider, str)
                else None
            ),
            route_model_id=resolved_route_model_id,
        )
        backup_path = None
        if changed:
            models_cache_path.parent.mkdir(parents=True, exist_ok=True)
            if existed:
                backup_path = models_cache_path.with_name(f"{models_cache_path.name}.bak.{utc_timestamp()}")
                shutil.copy2(models_cache_path, backup_path)
            write_json_file(models_cache_path, updated)
        return {
            "path": str(models_cache_path),
            "changed": changed,
            "created": (not existed) and changed,
            "backupPath": str(backup_path) if backup_path else None,
            "routeMode": "managed_provider",
        }

    providers = route_meta.get("providers")
    if not isinstance(providers, dict) or not providers:
        return {
            "path": str(models_cache_path),
            "changed": False,
            "created": False,
            "backupPath": None,
            "reason": "route_metadata_missing",
            "routeMode": OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
        }

    backup_path = None
    changed = False
    updated = config_data
    for entry in providers.values():
        if not isinstance(entry, dict):
            continue
        updated, entry_changed = _apply_preserve_provider_models_cache(updated, entry)
        changed = changed or entry_changed

    if changed:
        models_cache_path.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            backup_path = models_cache_path.with_name(f"{models_cache_path.name}.bak.{utc_timestamp()}")
            shutil.copy2(models_cache_path, backup_path)
        write_json_file(models_cache_path, updated)

    return {
        "path": str(models_cache_path),
        "changed": changed,
        "created": (not existed) and changed,
        "backupPath": str(backup_path) if backup_path else None,
        "routeMode": OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
    }


def remove_openclaw_models_cache_provider(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    force_remove: bool,
    auth_mode: str,
    native_provider: str | None,
) -> Tuple[Dict[str, Any], bool, Optional[str], str]:
    return _remove_managed_models_cache_provider(
        config,
        gateway_base_url,
        force_remove=force_remove,
        auth_mode=auth_mode,
        native_provider=native_provider,
    )


def uninstall_openclaw_models_cache_file(
    *,
    models_cache_path: Path,
    gateway_base_url: str,
    config_path: Path,
    force_remove: bool,
    auth_mode: str | None = None,
    native_provider: str | None = None,
) -> Dict[str, Any]:
    del native_provider
    if not models_cache_path.exists():
        return {
            "path": str(models_cache_path),
            "changed": False,
            "backupPath": None,
            "reason": "config_not_found",
            "removedBaseUrl": None,
        }

    config_data = read_json_file(models_cache_path)
    route_meta = _read_route_metadata(config_path)
    if _managed_metadata_mode(route_meta) or auth_mode == OPENCLAW_AUTH_MODE_MANAGED:
        resolved_auth_mode = str(route_meta.get("authMode") or auth_mode or OPENCLAW_AUTH_MODE_MANAGED)
        resolved_native_provider = route_meta.get("nativeProvider")
        updated, changed, removed_value, reason = _remove_managed_models_cache_provider(
            config_data,
            gateway_base_url,
            force_remove=force_remove,
            auth_mode=resolved_auth_mode,
            native_provider=(
                str(resolved_native_provider)
                if isinstance(resolved_native_provider, str)
                else None
            ),
        )

        backup_path = None
        if changed:
            backup_path = models_cache_path.with_name(f"{models_cache_path.name}.bak.{utc_timestamp()}")
            shutil.copy2(models_cache_path, backup_path)
            write_json_file(models_cache_path, updated)

        return {
            "path": str(models_cache_path),
            "changed": changed,
            "backupPath": str(backup_path) if backup_path else None,
            "reason": reason,
            "removedBaseUrl": removed_value,
            "routeMode": "managed_provider",
        }

    updated, changed, reason = _restore_preserve_provider_models_cache(
        config_data,
        gateway_base_url,
        force_remove=force_remove,
        route_meta=route_meta,
    )

    backup_path = None
    if changed:
        backup_path = models_cache_path.with_name(f"{models_cache_path.name}.bak.{utc_timestamp()}")
        shutil.copy2(models_cache_path, backup_path)
        write_json_file(models_cache_path, updated)

    return {
        "path": str(models_cache_path),
        "changed": changed,
        "backupPath": str(backup_path) if backup_path else None,
        "reason": reason,
        "routeMode": OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
    }
