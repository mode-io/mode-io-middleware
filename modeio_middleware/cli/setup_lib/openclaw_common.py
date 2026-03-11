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


def _normalize_api_family(provider_key: str, *provider_objects: Any) -> str | None:
    for provider_object in provider_objects:
        if not isinstance(provider_object, dict):
            continue
        api_family = _string_value(provider_object.get("api"))
        if api_family:
            return api_family.lower()
    normalized_provider = _normalize_provider_id(provider_key)
    if normalized_provider == "anthropic":
        return "anthropic-messages"
    if normalized_provider == "openai":
        return "openai-completions"
    return None


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
