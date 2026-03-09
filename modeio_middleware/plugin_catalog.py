#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from modeio_middleware.core.config_resolver import (
    PresetRegistry,
    resolve_plugin_runtime_config,
)
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.plugin_overrides import validate_plugin_overrides
from modeio_middleware.core.profiles import resolve_profile_plugins
from modeio_middleware.plugin_host import (
    load_plugin_host_config,
    resolve_plugin_host_command,
)
from modeio_middleware.protocol.manifest import PluginManifest, load_plugin_manifest


@dataclass(frozen=True)
class PluginDiscoverySettings:
    enabled: bool
    roots: List[Path]
    allow_symlinks: bool
    scan_hidden: bool


@dataclass
class PluginCatalogEntry:
    name: str
    source_kind: str
    plugin_config: Optional[Dict[str, Any]]
    manifest: Optional[PluginManifest] = None
    plugin_dir: Optional[Path] = None
    manifest_path: Optional[Path] = None
    host_path: Optional[Path] = None
    readme_path: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class PluginCatalog:
    entries: Dict[str, PluginCatalogEntry]
    runtime_plugins: Dict[str, Dict[str, Any]]
    discovery_roots: List[Path]
    warnings: List[str]


def _require_bool(raw: Any, *, source: str, default: bool) -> bool:
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"{source} must be boolean",
            retryable=False,
        )
    return raw


def _require_root_list(raw: Any, *, source: str) -> List[str]:
    if raw is None:
        return ["./plugins"]
    if not isinstance(raw, list):
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"{source} must be an array",
            retryable=False,
        )
    roots: List[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise MiddlewareError(
                500,
                "MODEIO_CONFIG_ERROR",
                f"{source}[{index}] must be a non-empty string",
                retryable=False,
            )
        roots.append(item.strip())
    return roots


def load_plugin_discovery_settings(
    config_payload: Dict[str, Any], *, config_file_path: Path
) -> PluginDiscoverySettings:
    raw = config_payload.get("plugin_discovery")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            "config.plugin_discovery must be an object",
            retryable=False,
        )

    roots: List[Path] = []
    for raw_root in _require_root_list(
        raw.get("roots"), source="config.plugin_discovery.roots"
    ):
        path = Path(raw_root)
        if not path.is_absolute():
            path = (config_file_path.parent / path).resolve()
        roots.append(path)

    return PluginDiscoverySettings(
        enabled=_require_bool(
            raw.get("enabled"), source="config.plugin_discovery.enabled", default=True
        ),
        roots=roots,
        allow_symlinks=_require_bool(
            raw.get("allow_symlinks"),
            source="config.plugin_discovery.allow_symlinks",
            default=False,
        ),
        scan_hidden=_require_bool(
            raw.get("scan_hidden"),
            source="config.plugin_discovery.scan_hidden",
            default=False,
        ),
    )


def _resolve_manifest_path(path_raw: Any, *, config_base_dir: Path) -> Path:
    if not isinstance(path_raw, str) or not path_raw.strip():
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            "stdio_jsonrpc plugin requires non-empty 'manifest' path",
            retryable=False,
        )
    path = Path(path_raw.strip())
    if not path.is_absolute():
        path = (config_base_dir / path).resolve()
    return path


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
    manifest: Optional[PluginManifest],
    *,
    readme_path: Optional[Path],
    fallback_name: str,
) -> Dict[str, Any]:
    metadata = manifest.metadata if manifest is not None else {}
    display_name = (
        metadata.get("display_name")
        if isinstance(metadata.get("display_name"), str)
        else fallback_name
    )
    description = (
        metadata.get("description")
        if isinstance(metadata.get("description"), str)
        else ""
    )
    if not description:
        description = _first_readme_paragraph(readme_path)
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


def _discover_entry(plugin_dir: Path) -> PluginCatalogEntry:
    manifest_path = plugin_dir / "manifest.json"
    host_path = plugin_dir / "modeio.host.json"
    readme_path = plugin_dir / "README.md"
    entry = PluginCatalogEntry(
        name=plugin_dir.name,
        source_kind="discovered",
        plugin_config=None,
        plugin_dir=plugin_dir,
        manifest_path=manifest_path if manifest_path.exists() else None,
        host_path=host_path if host_path.exists() else None,
        readme_path=readme_path if readme_path.exists() else None,
    )

    manifest: Optional[PluginManifest] = None
    if not manifest_path.exists():
        entry.errors.append(f"missing manifest.json in {plugin_dir}")
    else:
        try:
            manifest = load_plugin_manifest(manifest_path)
            entry.manifest = manifest
            entry.name = manifest.name
        except MiddlewareError as error:
            entry.errors.append(error.message)

    host_config = None
    if not host_path.exists():
        entry.errors.append(f"missing modeio.host.json in {plugin_dir}")
    else:
        try:
            host_config = load_plugin_host_config(host_path)
        except MiddlewareError as error:
            entry.errors.append(error.message)

    if manifest is None or host_config is None or entry.errors:
        return entry

    plugin_config: Dict[str, Any] = {
        "enabled": True,
        "runtime": host_config.runtime,
        "manifest": str(manifest_path.resolve()),
        "command": resolve_plugin_host_command(host_config, plugin_dir=plugin_dir),
        "mode": host_config.defaults.mode,
        "capabilities_grant": dict(host_config.defaults.capabilities_grant),
        "pool_size": host_config.defaults.pool_size,
    }
    if host_config.defaults.timeout_ms:
        plugin_config["timeout_ms"] = dict(host_config.defaults.timeout_ms)
    entry.plugin_config = plugin_config
    return entry


def _explicit_entry(
    plugin_name: str,
    plugin_config: Any,
    *,
    config_base_dir: Path,
) -> PluginCatalogEntry:
    entry = PluginCatalogEntry(
        name=plugin_name,
        source_kind="config",
        plugin_config=dict(plugin_config) if isinstance(plugin_config, dict) else None,
    )
    if not isinstance(plugin_config, dict):
        entry.errors.append(f"plugin '{plugin_name}' config is missing or invalid")
        return entry

    runtime = plugin_config.get("runtime")
    if not isinstance(runtime, str) or not runtime.strip():
        runtime = (
            "legacy_inprocess"
            if isinstance(plugin_config.get("module"), str)
            else "stdio_jsonrpc"
        )
    runtime = str(runtime).strip().lower()

    if runtime != "stdio_jsonrpc":
        return entry

    manifest_path_raw = plugin_config.get("manifest")
    try:
        manifest_path = _resolve_manifest_path(
            manifest_path_raw, config_base_dir=config_base_dir
        )
        manifest = load_plugin_manifest(manifest_path)
        entry.manifest = manifest
        entry.manifest_path = manifest_path
        entry.plugin_dir = manifest_path.parent
        readme_path = manifest_path.parent / "README.md"
        if readme_path.exists():
            entry.readme_path = readme_path
    except MiddlewareError as error:
        entry.errors.append(error.message)
    return entry


def build_plugin_catalog(
    config_payload: Dict[str, Any], *, config_file_path: Path
) -> PluginCatalog:
    raw_plugins = config_payload.get("plugins", {})
    if not isinstance(raw_plugins, dict):
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            "config.plugins must be an object",
            retryable=False,
        )

    settings = load_plugin_discovery_settings(
        config_payload, config_file_path=config_file_path
    )
    entries: Dict[str, PluginCatalogEntry] = {}
    warnings: List[str] = []
    runtime_plugins: Dict[str, Dict[str, Any]] = {}

    for plugin_name, plugin_config in raw_plugins.items():
        if not isinstance(plugin_name, str) or not plugin_name.strip():
            raise MiddlewareError(
                500,
                "MODEIO_CONFIG_ERROR",
                "config.plugins keys must be non-empty strings",
                retryable=False,
            )
        runtime_plugins[plugin_name.strip()] = plugin_config
        entries[plugin_name.strip()] = _explicit_entry(
            plugin_name.strip(),
            plugin_config,
            config_base_dir=config_file_path.parent,
        )

    if settings.enabled:
        for root in settings.roots:
            if not root.exists() or not root.is_dir():
                continue
            for child in sorted(root.iterdir(), key=lambda item: item.name):
                if not child.is_dir():
                    continue
                if child.name.startswith(".") and not settings.scan_hidden:
                    continue
                if child.is_symlink() and not settings.allow_symlinks:
                    warnings.append(f"skipped symlinked plugin directory: {child}")
                    continue

                entry = _discover_entry(child)
                if entry.name in entries:
                    warnings.append(
                        f"discovered plugin '{entry.name}' at {child} is shadowed by explicit config"
                    )
                    continue
                if entry.plugin_config is None:
                    warnings.extend(entry.errors)
                    continue
                entries[entry.name] = entry
                runtime_plugins[entry.name] = dict(entry.plugin_config)

    profiles = config_payload.get("profiles", {})
    if not isinstance(profiles, dict):
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            "config.profiles must be an object",
            retryable=False,
        )

    for profile_name, profile_config in profiles.items():
        if not isinstance(profile_name, str) or not profile_name.strip():
            raise MiddlewareError(
                500,
                "MODEIO_CONFIG_ERROR",
                "config.profiles keys must be non-empty strings",
                retryable=False,
            )
        if not isinstance(profile_config, dict):
            raise MiddlewareError(
                500,
                "MODEIO_CONFIG_ERROR",
                f"profile '{profile_name}' must be an object",
                retryable=False,
            )
        plugin_order = resolve_profile_plugins(profile_config)
        profile_overrides = validate_plugin_overrides(
            profile_config.get("plugin_overrides", {}),
            path_prefix="profile.plugin_overrides",
            object_error_message="profile.plugin_overrides must be an object",
            error_status=500,
            error_code="MODEIO_CONFIG_ERROR",
            allow_none=True,
        )
        referenced = set(plugin_order) | set(profile_overrides.keys())
        for plugin_name in referenced:
            if plugin_name in entries:
                continue
            entries[plugin_name] = PluginCatalogEntry(
                name=plugin_name,
                source_kind="missing",
                plugin_config=None,
                errors=[
                    f"plugin '{plugin_name}' is referenced by profile '{profile_name}' but not defined"
                ],
            )

    return PluginCatalog(
        entries=entries,
        runtime_plugins=runtime_plugins,
        discovery_roots=settings.roots,
        warnings=warnings,
    )


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
        metadata = _manifest_metadata(
            entry.manifest,
            readme_path=entry.readme_path,
            fallback_name=entry.name,
        )
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
