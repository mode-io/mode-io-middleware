#!/usr/bin/env python3

from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from modeio_middleware.cli.setup_lib.common import (
    build_client_gateway_base_url,
    SetupError,
    detect_os_name,
    ensure_object,
    read_json_file,
    utc_timestamp,
    write_json_file,
)

OPENAI_UPSTREAM_BASE_URL = "https://api.openai.com/v1"
OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER = "preserve_provider"
OPENCODE_UNSUPPORTED_OAUTH_PROVIDER_IDS = frozenset({"openai"})


def default_opencode_config_path(
    *,
    os_name: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    resolved_env = env or os.environ
    resolved_home = home or Path.home()
    system_name = detect_os_name(os_name)

    if system_name == "windows":
        app_data = resolved_env.get("APPDATA", "").strip()
        if app_data:
            return Path(app_data) / "opencode" / "opencode.json"
        return resolved_home / "AppData" / "Roaming" / "opencode" / "opencode.json"

    if system_name == "darwin":
        return resolved_home / ".config" / "opencode" / "opencode.json"

    xdg_home = resolved_env.get("XDG_CONFIG_HOME", "").strip()
    if xdg_home:
        return Path(xdg_home) / "opencode" / "opencode.json"
    return resolved_home / ".config" / "opencode" / "opencode.json"


def current_opencode_provider_id(config: Dict[str, Any]) -> str | None:
    model_name = config.get("model")
    if isinstance(model_name, str) and "/" in model_name:
        provider_id, _ = model_name.split("/", 1)
        if provider_id.strip():
            return provider_id.strip()
    return None


def _normalize_provider_id(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    return text or "openai"


def _route_metadata_path(config_path: Path) -> Path:
    return config_path.with_name(f"{config_path.name}.modeio-route.json")


def _env_mapping(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    return dict(env or os.environ)


def _read_route_metadata(config_path: Path) -> Dict[str, Any]:
    path = _route_metadata_path(config_path)
    if not path.exists():
        return {}
    return read_json_file(path)


def _write_route_metadata(config_path: Path, payload: Dict[str, Any]) -> None:
    write_json_file(_route_metadata_path(config_path), payload)


def _remove_route_metadata(config_path: Path) -> None:
    path = _route_metadata_path(config_path)
    if path.exists() or path.is_symlink():
        path.unlink()


def _provider_obj(config: Dict[str, Any], provider_id: str) -> Dict[str, Any]:
    provider_root = config.get("provider")
    if not isinstance(provider_root, dict):
        return {}
    provider_obj = provider_root.get(provider_id)
    return provider_obj if isinstance(provider_obj, dict) else {}


def _home(env: Dict[str, str]) -> Path:
    return Path(env.get("HOME", str(Path.home()))).expanduser()


def _opencode_auth_store_path(env: Dict[str, str]) -> Path:
    xdg_data = env.get("XDG_DATA_HOME", "").strip()
    if xdg_data:
        return Path(xdg_data).expanduser() / "opencode" / "auth.json"
    return _home(env) / ".local" / "share" / "opencode" / "auth.json"


def _opencode_auth_store(env: Dict[str, str]) -> Dict[str, Any]:
    path = _opencode_auth_store_path(env)
    try:
        payload = read_json_file(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _opencode_route_support(
    *,
    config: Dict[str, Any],
    config_path: Path,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    resolved_env = _env_mapping(env)
    provider_id = current_opencode_provider_id(config)
    if not provider_id:
        return {
            "providerId": None,
            "routeMode": OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER,
            "supported": False,
            "reason": "missing_active_provider",
            "configPath": str(config_path),
        }
    normalized_provider = _normalize_provider_id(provider_id)
    payload: Dict[str, Any] = {
        "providerId": provider_id,
        "routeMode": OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER,
        "supported": True,
    }
    auth_store_path = _opencode_auth_store_path(resolved_env)
    auth_entry = _opencode_auth_store(resolved_env).get(normalized_provider)
    if (
        normalized_provider in OPENCODE_UNSUPPORTED_OAUTH_PROVIDER_IDS
        and isinstance(auth_entry, dict)
        and str(auth_entry.get("type") or "").strip() == "oauth"
    ):
        payload.update(
            {
                "supported": False,
                "reason": "provider_uses_internal_oauth_transport",
                "configPath": str(config_path),
                "authStorePath": str(auth_store_path),
                "authType": "oauth",
            }
        )
    return payload


def _provider_base_url(provider_obj: Dict[str, Any]) -> str | None:
    options_obj = provider_obj.get("options")
    if isinstance(options_obj, dict):
        for field_name in ("baseURL", "baseUrl"):
            value = options_obj.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip().rstrip("/")
    for field_name in ("baseURL", "baseUrl"):
        value = provider_obj.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip("/")
    return None


def _default_upstream_base_url(provider_id: str) -> str | None:
    if _normalize_provider_id(provider_id) == "openai":
        return OPENAI_UPSTREAM_BASE_URL
    return None


def _is_loopback_base_url(base_url: str | None) -> bool:
    text = str(base_url or "").strip().lower()
    return text.startswith("http://127.0.0.1") or text.startswith("http://localhost")


def _resolve_preserved_upstream_base_url(
    config: Dict[str, Any],
    *,
    config_path: Path,
    provider_id: str,
) -> tuple[str | None, bool]:
    metadata = _read_route_metadata(config_path)
    providers = metadata.get("providers")
    if isinstance(providers, dict):
        entry = providers.get(_normalize_provider_id(provider_id))
        if isinstance(entry, dict):
            original = entry.get("originalBaseUrl")
            had_explicit = bool(entry.get("hadExplicitBaseUrl"))
            if isinstance(original, str) and original.strip():
                return original.strip().rstrip("/"), had_explicit

    provider_obj = _provider_obj(config, provider_id)
    current_base_url = _provider_base_url(provider_obj)
    if current_base_url and not _is_loopback_base_url(current_base_url):
        return current_base_url, True
    return _default_upstream_base_url(provider_id), False


def _write_provider_route_metadata(
    *,
    config_path: Path,
    provider_id: str,
    original_base_url: str,
    had_explicit_base_url: bool,
    gateway_base_url: str,
) -> None:
    metadata = _read_route_metadata(config_path)
    providers = metadata.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    providers[_normalize_provider_id(provider_id)] = {
        "providerId": _normalize_provider_id(provider_id),
        "originalBaseUrl": original_base_url,
        "hadExplicitBaseUrl": bool(had_explicit_base_url),
        "routeBaseUrl": build_client_gateway_base_url(
            gateway_base_url,
            "opencode",
            provider_name=provider_id,
        ),
        "routeMode": OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER,
    }
    metadata["providers"] = providers
    _write_route_metadata(config_path, metadata)


def apply_opencode_base_url(config: Dict[str, Any], gateway_base_url: str) -> Tuple[Dict[str, Any], bool]:
    updated = copy.deepcopy(config)
    provider_id = current_opencode_provider_id(updated)
    if not provider_id:
        raise SetupError("OpenCode config has no active provider/model to preserve")
    provider_obj = ensure_object(updated.get("provider"), "provider")
    selected_provider = ensure_object(
        provider_obj.get(provider_id), f"provider.{provider_id}"
    )
    options_obj = ensure_object(
        selected_provider.get("options"), f"provider.{provider_id}.options"
    )

    normalized = build_client_gateway_base_url(
        gateway_base_url,
        "opencode",
        provider_name=provider_id,
    )
    current_base_url = options_obj.get("baseURL")
    changed = current_base_url != normalized

    options_obj["baseURL"] = normalized
    selected_provider["options"] = options_obj
    provider_obj[provider_id] = selected_provider
    updated["provider"] = provider_obj
    return updated, changed


def remove_opencode_base_url(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    force_remove: bool,
) -> Tuple[Dict[str, Any], bool, Optional[str], str]:
    updated = copy.deepcopy(config)
    provider_id = current_opencode_provider_id(updated)
    if not provider_id:
        return updated, False, None, "missing_active_provider"

    provider_obj = updated.get("provider")
    if not isinstance(provider_obj, dict):
        return updated, False, None, "provider_missing"

    selected_provider = provider_obj.get(provider_id)
    if not isinstance(selected_provider, dict):
        return updated, False, None, f"{provider_id}_provider_missing"

    options_obj = selected_provider.get("options")
    if not isinstance(options_obj, dict):
        return updated, False, None, f"{provider_id}_options_missing"

    raw_base_url = options_obj.get("baseURL")
    if not isinstance(raw_base_url, str) or not raw_base_url.strip():
        return updated, False, None, "base_url_not_set"

    normalized_target = build_client_gateway_base_url(
        gateway_base_url,
        "opencode",
        provider_name=provider_id,
    )
    normalized_current = raw_base_url.rstrip("/")

    if not force_remove and normalized_current != normalized_target:
        return updated, False, raw_base_url, "base_url_mismatch"

    del options_obj["baseURL"]
    selected_provider["options"] = options_obj
    provider_obj[provider_id] = selected_provider
    updated["provider"] = provider_obj
    return updated, True, raw_base_url, "removed"


def apply_opencode_config_file(
    *,
    config_path: Path,
    gateway_base_url: str,
    create_if_missing: bool,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    existed = config_path.exists()
    if not existed and not create_if_missing:
        raise SetupError(
            f"OpenCode config not found: {config_path}. Middleware expects an existing, working OpenCode config."
        )

    config_data: Dict[str, Any] = {}
    if existed:
        config_data = read_json_file(config_path)

    route_support = _opencode_route_support(
        config=config_data,
        config_path=config_path,
        env=env,
    )
    provider_id = route_support.get("providerId") or current_opencode_provider_id(config_data)
    if not route_support.get("supported", True):
        return {
            "path": str(config_path),
            "changed": False,
            "created": False,
            "backupPath": None,
            "providerId": provider_id,
            "routeMode": OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER,
            "supported": False,
            "reason": route_support.get("reason") or "unsupported_provider_transport",
            "configPath": route_support.get("configPath"),
            "authStorePath": route_support.get("authStorePath"),
            "authType": route_support.get("authType"),
        }
    if not provider_id:
        return {
            "path": str(config_path),
            "changed": False,
            "created": False,
            "backupPath": None,
            "providerId": None,
            "routeMode": OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER,
            "supported": False,
            "reason": "missing_active_provider",
        }

    original_base_url, had_explicit_base_url = _resolve_preserved_upstream_base_url(
        config_data,
        config_path=config_path,
        provider_id=provider_id,
    )
    if not original_base_url:
        return {
            "path": str(config_path),
            "changed": False,
            "created": False,
            "backupPath": None,
            "providerId": provider_id,
            "routeMode": OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER,
            "supported": False,
            "reason": "missing_upstream_base_url",
        }

    updated, changed = apply_opencode_base_url(config_data, gateway_base_url)
    backup_path = None
    if changed:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if existed:
            backup_path = config_path.with_name(f"{config_path.name}.bak.{utc_timestamp()}")
            shutil.copy2(config_path, backup_path)
        write_json_file(config_path, updated)
    if changed or existed or create_if_missing:
        _write_provider_route_metadata(
            config_path=config_path,
            provider_id=provider_id,
            original_base_url=original_base_url,
            had_explicit_base_url=had_explicit_base_url,
            gateway_base_url=gateway_base_url,
        )

    return {
        "path": str(config_path),
        "changed": changed,
        "created": (not existed) and changed,
        "backupPath": str(backup_path) if backup_path else None,
        "providerId": provider_id,
        "originalBaseUrl": original_base_url,
        "routeMode": OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER,
        "supported": True,
    }


def uninstall_opencode_config_file(
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
    provider_id = current_opencode_provider_id(config_data)
    if not provider_id:
        return {
            "path": str(config_path),
            "changed": False,
            "backupPath": None,
            "reason": "missing_active_provider",
            "removedBaseUrl": None,
            "providerId": None,
            "routeMode": OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER,
        }
    metadata = _read_route_metadata(config_path)
    providers = metadata.get("providers")
    entry = providers.get(_normalize_provider_id(provider_id)) if isinstance(providers, dict) else None
    updated = copy.deepcopy(config_data)
    changed = False
    removed_value = None
    reason = "base_url_not_set"
    provider_root = ensure_object(updated.get("provider"), "provider")
    provider_obj = ensure_object(provider_root.get(provider_id), f"provider.{provider_id}")
    options_obj = ensure_object(provider_obj.get("options"), f"provider.{provider_id}.options")
    current_base_url = options_obj.get("baseURL")
    normalized_target = build_client_gateway_base_url(
        gateway_base_url,
        "opencode",
        provider_name=provider_id,
    )

    if (
        isinstance(current_base_url, str)
        and current_base_url.strip()
        and (force_remove or current_base_url.rstrip("/") == normalized_target)
    ):
        removed_value = current_base_url
        if isinstance(entry, dict) and isinstance(entry.get("originalBaseUrl"), str):
            if bool(entry.get("hadExplicitBaseUrl")):
                options_obj["baseURL"] = str(entry["originalBaseUrl"]).rstrip("/")
                reason = "restored"
            else:
                options_obj.pop("baseURL", None)
                reason = "removed"
        else:
            options_obj.pop("baseURL", None)
            reason = "removed"
        provider_obj["options"] = options_obj
        provider_root[provider_id] = provider_obj
        updated["provider"] = provider_root
        changed = True
    elif isinstance(current_base_url, str) and current_base_url.strip():
        removed_value = current_base_url
        reason = "base_url_mismatch"

    backup_path = None
    if changed:
        backup_path = config_path.with_name(f"{config_path.name}.bak.{utc_timestamp()}")
        shutil.copy2(config_path, backup_path)
        write_json_file(config_path, updated)
        if isinstance(providers, dict):
            providers.pop(_normalize_provider_id(provider_id), None)
            if providers:
                metadata["providers"] = providers
                _write_route_metadata(config_path, metadata)
            else:
                _remove_route_metadata(config_path)

    return {
        "path": str(config_path),
        "changed": changed,
        "backupPath": str(backup_path) if backup_path else None,
        "reason": reason,
        "removedBaseUrl": removed_value,
        "providerId": provider_id,
        "routeMode": OPENCODE_ROUTE_MODE_PRESERVE_PROVIDER,
    }
