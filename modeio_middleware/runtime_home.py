#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from modeio_middleware.cli.setup_lib.common import detect_os_name
from modeio_middleware.resources import (
    bundled_default_config_path,
    bundled_example_plugin_dir,
)

MODEIO_HOME_ENV = "MODEIO_HOME"
MODEIO_CONFIG_ENV = "MODEIO_MIDDLEWARE_CONFIG"


def default_modeio_home_path(
    *,
    os_name: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    resolved_env = env or os.environ
    explicit_home = resolved_env.get(MODEIO_HOME_ENV, "").strip()
    if explicit_home:
        return Path(explicit_home).expanduser()

    resolved_home = home or Path.home()
    system_name = detect_os_name(os_name)

    if system_name == "windows":
        app_data = resolved_env.get("APPDATA", "").strip()
        if app_data:
            return Path(app_data) / "ModeIO"
        return resolved_home / "AppData" / "Roaming" / "ModeIO"

    if system_name == "darwin":
        return resolved_home / ".config" / "modeio"

    xdg_home = resolved_env.get("XDG_CONFIG_HOME", "").strip()
    if xdg_home:
        return Path(xdg_home) / "modeio"
    return resolved_home / ".config" / "modeio"


def default_modeio_config_path(
    *,
    os_name: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    resolved_env = env or os.environ
    explicit_config = resolved_env.get(MODEIO_CONFIG_ENV, "").strip()
    if explicit_config:
        return Path(explicit_config).expanduser()
    return (
        default_modeio_home_path(os_name=os_name, env=resolved_env, home=home)
        / "middleware.json"
    )


def default_modeio_plugins_path(
    *,
    os_name: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
) -> Path:
    return (
        default_modeio_config_path(os_name=os_name, env=env, home=home).parent
        / "plugins"
    )


def build_user_runtime_config_payload() -> Dict[str, Any]:
    bundled_payload = json.loads(
        bundled_default_config_path().read_text(encoding="utf-8")
    )
    return {
        "version": "0.2",
        "profiles": bundled_payload.get("profiles", {}),
        "plugins": {},
        "plugin_discovery": {
            "enabled": True,
            "roots": ["./plugins"],
            "allow_symlinks": False,
            "scan_hidden": False,
        },
        "services": bundled_payload.get("services", {}),
    }


def ensure_user_runtime_home(config_path: Path) -> bool:
    target = config_path.expanduser()
    if target.exists():
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    plugins_dir = target.parent / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    payload = build_user_runtime_config_payload()
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    example_source = bundled_example_plugin_dir()
    example_target = plugins_dir / "example"
    if example_source.exists() and not example_target.exists():
        shutil.copytree(example_source, example_target)

    return True
