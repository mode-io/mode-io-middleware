#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEV_RUNTIME_DIRNAME = ".modeio-dev"
DEV_INSTANCE_ID_ENV = "MODEIO_DEV_INSTANCE_ID"
DEFAULT_GATEWAY_HOST = "127.0.0.1"
DEFAULT_GATEWAY_PORT = 8787
DEFAULT_DASHBOARD_DEV_PORT = 4173


@dataclass(frozen=True)
class DevRuntimePaths:
    repo_root: Path
    runtime_home: Path
    config_path: Path
    plugins_dir: Path
    backups_dir: Path
    dashboard_source_dir: Path
    dashboard_bundle_dir: Path


def resolve_dev_runtime_paths(
    repo_root: Path, runtime_home: Path | None = None
) -> DevRuntimePaths:
    root = repo_root.resolve()
    resolved_runtime_home = (runtime_home or (root / DEV_RUNTIME_DIRNAME)).resolve()
    return DevRuntimePaths(
        repo_root=root,
        runtime_home=resolved_runtime_home,
        config_path=resolved_runtime_home / "middleware.json",
        plugins_dir=resolved_runtime_home / "plugins",
        backups_dir=resolved_runtime_home / "backups",
        dashboard_source_dir=root / "dashboard",
        dashboard_bundle_dir=root / "modeio_middleware" / "resources" / "dashboard",
    )


def should_use_dev_runtime(
    gateway_args: list[str], env: Mapping[str, str] | None = None
) -> bool:
    resolved_env = env or os.environ
    if resolved_env.get("MODEIO_HOME") or resolved_env.get("MODEIO_MIDDLEWARE_CONFIG"):
        return False
    for arg in gateway_args:
        if arg == "--config" or arg.startswith("--config="):
            return False
    return True


def dev_instance_id(runtime_home: Path) -> str:
    normalized = str(runtime_home.expanduser().resolve())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def apply_dev_runtime_env(
    *,
    runtime_home: Path,
    env: Mapping[str, str] | None = None,
    force: bool = False,
) -> dict[str, str]:
    resolved_env = dict(os.environ if env is None else env)
    if force or (
        not resolved_env.get("MODEIO_HOME")
        and not resolved_env.get("MODEIO_MIDDLEWARE_CONFIG")
    ):
        resolved_env["MODEIO_HOME"] = str(runtime_home)
    resolved_env[DEV_INSTANCE_ID_ENV] = dev_instance_id(runtime_home)
    return resolved_env


def reset_dev_runtime(runtime_home: Path) -> None:
    target = runtime_home.expanduser()
    if target.exists():
        shutil.rmtree(target)


def dashboard_bundle_exists(paths: DevRuntimePaths) -> bool:
    return (
        (paths.dashboard_bundle_dir / "index.html").exists()
        and (paths.dashboard_bundle_dir / "assets" / "dashboard.js").exists()
        and (paths.dashboard_bundle_dir / "assets" / "dashboard.css").exists()
    )


def dashboard_bundle_is_stale(paths: DevRuntimePaths) -> bool:
    if not dashboard_bundle_exists(paths):
        return True
    if not paths.dashboard_source_dir.exists():
        return False

    source_paths = [
        path
        for path in paths.dashboard_source_dir.rglob("*")
        if path.is_file() and "node_modules" not in path.parts
    ]
    if not source_paths:
        return False

    bundle_paths = [
        paths.dashboard_bundle_dir / "index.html",
        paths.dashboard_bundle_dir / "assets" / "dashboard.js",
        paths.dashboard_bundle_dir / "assets" / "dashboard.css",
    ]
    newest_source = max(path.stat().st_mtime for path in source_paths)
    oldest_bundle = min(path.stat().st_mtime for path in bundle_paths)
    return newest_source > oldest_bundle


def review_url(host: str = DEFAULT_GATEWAY_HOST, port: int = DEFAULT_GATEWAY_PORT) -> str:
    return f"http://{host}:{port}/modeio/dashboard"


def health_url(host: str = DEFAULT_GATEWAY_HOST, port: int = DEFAULT_GATEWAY_PORT) -> str:
    return f"http://{host}:{port}/healthz"


def vite_dashboard_url(port: int = DEFAULT_DASHBOARD_DEV_PORT) -> str:
    return f"http://127.0.0.1:{port}/modeio/dashboard/"
