#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from modeio_middleware.core.config_resolver import (
    PresetRegistry,
    resolve_plugin_runtime_config,
)
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.plugin_overrides import validate_plugin_overrides
from modeio_middleware.core.profiles import resolve_profile_plugins
from modeio_middleware.plugin_catalog_discovery import build_plugin_catalog
from modeio_middleware.plugin_catalog_models import PluginCatalogEntry


def _default_declared_capabilities() -> Dict[str, bool]:
    return {
        "canPatch": False,
        "canBlock": False,
        "needsNetwork": False,
        "needsRawBody": False,
    }


def _first_readme_paragraph(path: Optional[Path]) -> str:
    if path is None or not path.exists():
        return ""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""

    lines = [line.strip() for line in raw.splitlines()]
    paragraph: List[str] = []
    started = False
    for line in lines:
        if not line:
            if started and paragraph:
                break
            continue
        if not started and line.startswith("#"):
            continue
        started = True
        paragraph.append(line)
    return " ".join(paragraph).strip()


def _manifest_metadata(
    entry: PluginCatalogEntry,
) -> Dict[str, Any]:
    manifest = entry.manifest
    metadata = manifest.metadata if manifest is not None else {}
    display_name = (
        metadata.get("display_name")
        if isinstance(metadata.get("display_name"), str)
        else entry.name
    )
    description = (
        metadata.get("description")
        if isinstance(metadata.get("description"), str)
        else ""
    )
    if not description:
        description = _first_readme_paragraph(entry.readme_path)
    return {
        "displayName": display_name,
        "description": description,
        "metadata": metadata,
        "version": manifest.version if manifest is not None else "",
        "hooks": list(manifest.hooks) if manifest is not None else [],
        "declaredCapabilities": {
            "canPatch": bool(manifest.capabilities.get("can_patch", False))
            if manifest is not None
            else False,
            "canBlock": bool(manifest.capabilities.get("can_block", False))
            if manifest is not None
            else False,
            "needsNetwork": bool(manifest.capabilities.get("needs_network", False))
            if manifest is not None
            else False,
            "needsRawBody": bool(manifest.capabilities.get("needs_raw_body", False))
            if manifest is not None
            else False,
        }
        if manifest is not None
        else _default_declared_capabilities(),
    }


def build_plugin_inventory_response(
    config_payload: Dict[str, Any],
    *,
    config_file_path: Path,
    preset_registry: PresetRegistry,
    generation: int,
    default_profile: str,
    config_writable: bool,
    stats_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    catalog = build_plugin_catalog(config_payload, config_file_path=config_file_path)
    profiles_payload = config_payload.get("profiles", {})
    by_plugin_stats = {}
    if isinstance(stats_snapshot, dict):
        raw_by_plugin = stats_snapshot.get("byPlugin", {})
        if isinstance(raw_by_plugin, dict):
            by_plugin_stats = raw_by_plugin

    profiles: List[Dict[str, Any]] = []
    for profile_name in sorted(profiles_payload.keys()):
        profile_config = profiles_payload[profile_name]
        plugin_order = resolve_profile_plugins(profile_config)
        profiles.append(
            {
                "name": profile_name,
                "onPluginError": str(profile_config.get("on_plugin_error", "warn")),
                "pluginOrder": list(plugin_order),
            }
        )

    plugin_entries: List[Dict[str, Any]] = []
    for entry in sorted(catalog.entries.values(), key=lambda item: item.name):
        metadata = _manifest_metadata(entry)
        validation_warnings = list(entry.warnings)
        validation_errors = list(entry.errors)
        profile_states: Dict[str, Any] = {}

        for profile_name in sorted(profiles_payload.keys()):
            profile_config = profiles_payload[profile_name]
            plugin_order = resolve_profile_plugins(profile_config)
            positions = {name: index for index, name in enumerate(plugin_order)}
            profile_overrides = validate_plugin_overrides(
                profile_config.get("plugin_overrides", {}),
                path_prefix="profile.plugin_overrides",
                object_error_message="profile.plugin_overrides must be an object",
                error_status=500,
                error_code="MODEIO_CONFIG_ERROR",
                allow_none=True,
            )
            listed = entry.name in positions
            position = positions.get(entry.name)
            override = dict(profile_overrides.get(entry.name, {}))
            state: Dict[str, Any] = {
                "listed": listed,
                "enabled": False,
                "position": position,
                "override": override,
            }

            if entry.plugin_config is not None:
                try:
                    resolved = resolve_plugin_runtime_config(
                        plugin_name=entry.name,
                        plugin_config=entry.plugin_config,
                        preset_registry=preset_registry,
                        profile_override=override,
                        request_override={},
                    )
                    state.update(
                        {
                            "enabled": listed and resolved.enabled,
                            "effectiveMode": resolved.config.get("mode"),
                            "effectiveCapabilitiesGrant": dict(
                                resolved.config.get("capabilities_grant", {})
                            )
                            if isinstance(
                                resolved.config.get("capabilities_grant"), dict
                            )
                            else {"can_patch": False, "can_block": False},
                            "effectivePoolSize": resolved.config.get("pool_size", 1),
                            "effectiveTimeoutMs": dict(
                                resolved.config.get("timeout_ms", {})
                            )
                            if isinstance(resolved.config.get("timeout_ms"), dict)
                            else {},
                        }
                    )
                except MiddlewareError as error:
                    validation_errors.append(error.message)

            profile_states[profile_name] = state

        stats = by_plugin_stats.get(entry.name, {})
        if not isinstance(stats, dict):
            stats = {}
        validation_status = (
            "error" if validation_errors else ("warn" if validation_warnings else "ok")
        )
        plugin_entries.append(
            {
                "name": entry.name,
                "displayName": metadata["displayName"],
                "description": metadata["description"],
                "sourceKind": entry.source_kind,
                "version": metadata["version"],
                "hooks": metadata["hooks"],
                "declaredCapabilities": metadata["declaredCapabilities"],
                "metadata": metadata["metadata"],
                "pluginDir": str(entry.plugin_dir)
                if entry.plugin_dir is not None
                else None,
                "manifestPath": str(entry.manifest_path)
                if entry.manifest_path is not None
                else None,
                "hostPath": str(entry.host_path)
                if entry.host_path is not None
                else None,
                "readmePath": str(entry.readme_path)
                if entry.readme_path is not None
                else None,
                "profiles": profile_states,
                "validation": {
                    "status": validation_status,
                    "warnings": validation_warnings,
                    "errors": validation_errors,
                },
                "stats": {
                    "calls": int(stats.get("calls", 0))
                    if isinstance(stats.get("calls", 0), int)
                    else 0,
                    "errors": int(stats.get("errors", 0))
                    if isinstance(stats.get("errors", 0), int)
                    else 0,
                    "actions": dict(stats.get("actions", {}))
                    if isinstance(stats.get("actions", {}), dict)
                    else {},
                },
            }
        )

    return {
        "runtime": {
            "configPath": str(config_file_path),
            "configWritable": config_writable,
            "generation": generation,
            "defaultProfile": default_profile,
            "discoveryRoots": [str(root) for root in catalog.discovery_roots],
        },
        "profiles": profiles,
        "plugins": plugin_entries,
        "warnings": list(catalog.warnings),
    }
