#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from modeio_middleware.cli.setup_lib.common import (
    SetupError,
    detect_os_name,
    ensure_object,
    read_json_file,
    utc_timestamp,
    write_json_file,
)
from modeio_middleware.core.provider_policy import (
    OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
    OPENCLAW_SUPPORTED_API_FAMILIES,
    normalize_provider_id as _policy_normalize_provider_id,
    openclaw_provider_gateway_base_url,
    resolve_openclaw_api_family,
    route_metadata_entry as _route_metadata_entry,
    string_value as _policy_string_value,
)

OPENCLAW_PROVIDER_ID = "modeio-middleware"
OPENCLAW_MODEL_ID = "middleware-default"
OPENCLAW_MODEL_REF = f"{OPENCLAW_PROVIDER_ID}/{OPENCLAW_MODEL_ID}"
OPENCLAW_MODEL_NAME = "Modeio Middleware Default"
OPENCLAW_DEFAULT_API_KEY = "modeio-middleware"
OPENCLAW_AUTH_MODE_NATIVE = "native"
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


def _string_value(value: Any) -> str | None:
    return _policy_string_value(value)


def _normalize_provider_id(raw_provider_id: str | None) -> str:
    return _policy_normalize_provider_id(raw_provider_id)


def _provider_gateway_base_url(
    gateway_base_url: str,
    *,
    provider_key: str,
    api_family: str,
) -> str:
    return openclaw_provider_gateway_base_url(
        gateway_base_url,
        provider_key=provider_key,
        api_family=api_family,
    )


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


def _normalize_api_family(provider_key: str, *provider_objects: Any) -> str | None:
    return resolve_openclaw_api_family(provider_key, *provider_objects)


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
    return _route_metadata_entry(existing_route_metadata, provider_id)
