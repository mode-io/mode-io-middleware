#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.plugin_overrides import validate_plugin_overrides
from modeio_middleware.core.profiles import resolve_profile_plugins
from modeio_middleware.plugin_catalog_models import (
    PluginCatalog,
    PluginCatalogEntry,
    PluginDiscoverySettings,
)
from modeio_middleware.plugin_host import (
    load_plugin_host_config,
    resolve_plugin_host_command,
)
from modeio_middleware.protocol.manifest import load_plugin_manifest


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

    manifest = None
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
