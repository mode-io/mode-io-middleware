#!/usr/bin/env python3

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from modeio_middleware.cli.setup_lib.openclaw_common import (
    OPENCLAW_AUTH_MODE_NATIVE,
    OPENCLAW_MODEL_ID,
    OPENCLAW_ROUTE_MODE_PRESERVE_PROVIDER,
    SetupError,
    _read_route_metadata,
    _remove_route_metadata,
    _write_route_metadata,
    read_json_file,
    utc_timestamp,
    write_json_file,
)
from modeio_middleware.cli.setup_lib.openclaw_routes import (
    _apply_preserve_provider_models_cache,
    _apply_preserve_provider_route,
    _remove_managed_models_cache_provider,
    _remove_managed_provider_route,
    _resolve_preserve_provider_target,
    _restore_preserve_provider_config,
    _restore_preserve_provider_models_cache,
    _managed_metadata_mode,
    _write_preserve_provider_metadata,
)


def apply_openclaw_provider_route(
    config: Dict[str, Any],
    gateway_base_url: str,
    *,
    auth_mode: str = OPENCLAW_AUTH_MODE_NATIVE,
    existing_route_metadata: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], bool]:
    if auth_mode != OPENCLAW_AUTH_MODE_NATIVE:
        raise SetupError("OpenClaw managed mode is no longer supported")
    route_metadata = existing_route_metadata or {}
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
    auth_mode: str = OPENCLAW_AUTH_MODE_NATIVE,
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
    auth_mode: str = OPENCLAW_AUTH_MODE_NATIVE,
    models_cache_path: Path | None = None,
) -> Dict[str, Any]:
    if auth_mode != OPENCLAW_AUTH_MODE_NATIVE:
        raise SetupError("OpenClaw managed mode is no longer supported")
    existed = config_path.exists()
    if not existed and not create_if_missing:
        raise SetupError(
            f"OpenClaw config not found: {config_path}. Middleware expects an existing, working OpenClaw config."
        )

    config_data: Dict[str, Any] = {}
    if existed:
        config_data = read_json_file(config_path)
    models_cache_data: Dict[str, Any] | None = None
    if models_cache_path is not None and models_cache_path.exists():
        models_cache_data = read_json_file(models_cache_path)
    existing_route_metadata = _read_route_metadata(config_path)

    route_target = _resolve_preserve_provider_target(
        config_data,
        gateway_base_url,
        models_cache_data=models_cache_data,
        existing_route_metadata=existing_route_metadata,
    )
    if not route_target.get("supported"):
        return {
            "path": str(config_path),
            "changed": False,
            "created": False,
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
    if auth_mode not in {None, OPENCLAW_AUTH_MODE_NATIVE}:
        raise SetupError("OpenClaw managed mode is no longer supported")
    existed = models_cache_path.exists()

    config_data: Dict[str, Any] = {}
    if existed:
        config_data = read_json_file(models_cache_path)

    route_meta = _read_route_metadata(config_path)
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
    if _managed_metadata_mode(route_meta):
        resolved_auth_mode = str(route_meta.get("authMode") or "managed")
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
