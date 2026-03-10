#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from modeio_middleware.protocol.manifest import PluginManifest


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
