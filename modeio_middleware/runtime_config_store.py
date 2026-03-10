#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

from modeio_middleware.cli.setup_lib.common import utc_timestamp
from modeio_middleware.core.config_resolver import load_preset_registry
from modeio_middleware.core.engine import GatewayRuntimeConfig
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.profiles import DEFAULT_PROFILE, normalize_profile_name
from modeio_middleware.plugin_catalog_discovery import build_plugin_catalog


def read_runtime_config_payload(path: Path) -> Dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise MiddlewareError(
            500, "MODEIO_CONFIG_ERROR", f"failed to read config file: {path}"
        ) from error

    try:
        payload = json.loads(content)
    except ValueError as error:
        raise MiddlewareError(
            500, "MODEIO_CONFIG_ERROR", f"invalid JSON config: {path}"
        ) from error

    if not isinstance(payload, dict):
        raise MiddlewareError(
            500, "MODEIO_CONFIG_ERROR", "middleware config root must be an object"
        )
    return payload


def build_gateway_runtime_config(
    config_path: Path,
    *,
    upstream_chat_completions_url: str,
    upstream_responses_url: str,
    upstream_timeout_seconds: int,
    upstream_api_key_env: str,
    default_profile: str = DEFAULT_PROFILE,
) -> GatewayRuntimeConfig:
    payload = read_runtime_config_payload(config_path)
    return build_gateway_runtime_config_from_payload(
        payload,
        config_path=config_path,
        upstream_chat_completions_url=upstream_chat_completions_url,
        upstream_responses_url=upstream_responses_url,
        upstream_timeout_seconds=upstream_timeout_seconds,
        upstream_api_key_env=upstream_api_key_env,
        default_profile=default_profile,
    )


def build_gateway_runtime_config_from_payload(
    payload: Dict[str, Any],
    *,
    config_path: Path,
    upstream_chat_completions_url: str,
    upstream_responses_url: str,
    upstream_timeout_seconds: int,
    upstream_api_key_env: str,
    default_profile: str = DEFAULT_PROFILE,
) -> GatewayRuntimeConfig:
    profiles = payload.get("profiles", {})
    services = payload.get("services", {})
    if not isinstance(profiles, dict):
        raise MiddlewareError(
            500, "MODEIO_CONFIG_ERROR", "config.profiles must be an object"
        )
    if not isinstance(services, dict):
        raise MiddlewareError(
            500, "MODEIO_CONFIG_ERROR", "config.services must be an object"
        )

    catalog = build_plugin_catalog(payload, config_file_path=config_path)
    preset_registry = load_preset_registry(payload, config_file_path=config_path)

    return GatewayRuntimeConfig(
        upstream_chat_completions_url=upstream_chat_completions_url,
        upstream_responses_url=upstream_responses_url,
        upstream_timeout_seconds=upstream_timeout_seconds,
        upstream_api_key_env=upstream_api_key_env,
        default_profile=normalize_profile_name(
            default_profile, default_profile=DEFAULT_PROFILE
        ),
        profiles=profiles,
        plugins=catalog.runtime_plugins,
        preset_registry=preset_registry,
        service_config=services,
        config_base_dir=str(config_path.parent),
        config_path=str(config_path),
    )


def is_runtime_config_writable(path: Path) -> bool:
    target = path.expanduser()
    if target.exists():
        return os.access(target, os.W_OK)
    parent = target.parent if target.parent != Path("") else Path.cwd()
    return parent.exists() and os.access(parent, os.W_OK)


def write_runtime_config_payload(path: Path, payload: Dict[str, Any]) -> str:
    target = path.expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)

        backup_dir = target.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{target.stem}.{utc_timestamp()}{target.suffix}"
        if target.exists():
            shutil.copy2(target, backup_path)
        else:
            backup_path.write_text("", encoding="utf-8")

        body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    except OSError as error:
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"failed to write config file: {target}",
            retryable=False,
        ) from error
    return str(backup_path)
