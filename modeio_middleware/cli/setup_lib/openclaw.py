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


def _resolve_route_target(
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


def apply_openclaw_provider_route(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    auth_mode: str,
    existing_route_metadata: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], bool]:
    updated = copy.deepcopy(config)
    changed = False
    target = _resolve_route_target(
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


def apply_openclaw_models_cache_provider(
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

    models_obj = updated.get("models")
    root_providers_obj = updated.get("providers")
    if isinstance(models_obj, dict):
        models_obj = ensure_object(models_obj, "models")
        providers_obj = ensure_object(models_obj.get("providers"), "models.providers")
        provider_parent = "models"
    elif isinstance(root_providers_obj, dict):
        providers_obj = ensure_object(root_providers_obj, "providers")
        provider_parent = "root"
    elif models_obj is None:
        models_obj = ensure_object(models_obj, "models")
        providers_obj = ensure_object(models_obj.get("providers"), "models.providers")
        provider_parent = "models"
    else:
        providers_obj = ensure_object(updated.get("providers"), "providers")
        provider_parent = "root"

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
        models_obj["providers"] = providers_obj
        updated["models"] = models_obj
    else:
        updated["providers"] = providers_obj
    return updated, changed


def remove_openclaw_models_cache_provider(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    force_remove: bool,
    auth_mode: str,
    native_provider: str | None,
) -> Tuple[Dict[str, Any], bool, Optional[str], str]:
    updated = copy.deepcopy(config)

    models_obj = updated.get("models")
    root_providers_obj = updated.get("providers")
    if isinstance(models_obj, dict):
        providers_obj = models_obj.get("providers")
        provider_parent = "models"
    elif isinstance(root_providers_obj, dict):
        providers_obj = root_providers_obj
        provider_parent = "root"
    else:
        providers_obj = updated.get("providers")
        provider_parent = "root"

    if not isinstance(providers_obj, dict):
        if provider_parent == "models":
            providers_obj = updated.get("providers")
            provider_parent = "root"
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
        models_obj["providers"] = providers_obj
        updated["models"] = models_obj
    else:
        updated["providers"] = providers_obj
    return updated, True, removed_base_url, "removed"


def apply_openclaw_config_file(
    *,
    config_path: Path,
    gateway_base_url: str,
    create_if_missing: bool,
    auth_mode: str,
) -> Dict[str, Any]:
    existed = config_path.exists()
    if not existed and not create_if_missing:
        raise SetupError(
            f"OpenClaw config not found: {config_path}. Use --create-openclaw-config to create it."
        )

    config_data: Dict[str, Any] = {}
    if existed:
        config_data = read_json_file(config_path)
    route_target = _resolve_route_target(
        config_data,
        auth_mode,
        existing_route_metadata=_read_route_metadata(config_path),
    )

    updated, changed = apply_openclaw_provider_route(
        config_data,
        gateway_base_url,
        auth_mode=auth_mode,
        existing_route_metadata=_read_route_metadata(config_path),
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
    auth_mode = str(route_meta.get("authMode") or OPENCLAW_AUTH_MODE_MANAGED)
    native_provider = route_meta.get("nativeProvider")
    route_model_id = str(route_meta.get("routeModelId") or OPENCLAW_MODEL_ID)
    previous_primary = route_meta.get("previousPrimary")
    updated, changed, removed_value, reason = remove_openclaw_provider_route(
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
    }


def apply_openclaw_models_cache_file(
    *,
    models_cache_path: Path,
    gateway_base_url: str,
    auth_mode: str,
    native_provider: str | None,
    route_model_id: str,
) -> Dict[str, Any]:
    existed = models_cache_path.exists()

    config_data: Dict[str, Any] = {}
    if existed:
        config_data = read_json_file(models_cache_path)

    updated, changed = apply_openclaw_models_cache_provider(
        config_data,
        gateway_base_url,
        auth_mode=auth_mode,
        native_provider=native_provider,
        route_model_id=route_model_id,
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
    }


def uninstall_openclaw_models_cache_file(
    *,
    models_cache_path: Path,
    gateway_base_url: str,
    force_remove: bool,
    auth_mode: str,
    native_provider: str | None,
) -> Dict[str, Any]:
    if not models_cache_path.exists():
        return {
            "path": str(models_cache_path),
            "changed": False,
            "backupPath": None,
            "reason": "config_not_found",
            "removedBaseUrl": None,
        }

    config_data = read_json_file(models_cache_path)
    updated, changed, removed_value, reason = remove_openclaw_models_cache_provider(
        config_data,
        gateway_base_url,
        force_remove=force_remove,
        auth_mode=auth_mode,
        native_provider=native_provider,
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
    }
