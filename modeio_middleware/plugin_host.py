#!/usr/bin/env python3

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.registry.resolver import VALID_MODES


@dataclass(frozen=True)
class PluginHostDefaults:
    mode: str
    capabilities_grant: Dict[str, bool]
    pool_size: int
    timeout_ms: Dict[str, int]


@dataclass(frozen=True)
class PluginHostConfig:
    version: str
    runtime: str
    command: List[str]
    working_directory: str
    defaults: PluginHostDefaults
    source_path: str


def _require_object(value: Any, *, source: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise MiddlewareError(
        500,
        "MODEIO_CONFIG_ERROR",
        f"{source} must be an object",
        retryable=False,
    )


def _require_string(value: Any, *, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"{source} must be a non-empty string",
            retryable=False,
        )
    return value.strip()


def _require_command(raw: Any, *, source: str) -> List[str]:
    if not isinstance(raw, list) or not raw:
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"{source} must be a non-empty array",
            retryable=False,
        )

    command: List[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise MiddlewareError(
                500,
                "MODEIO_CONFIG_ERROR",
                f"{source}[{index}] must be a non-empty string",
                retryable=False,
            )
        command.append(item.strip())
    return command


def _normalize_mode(raw: Any, *, source: str) -> str:
    if raw is None:
        return "observe"
    value = _require_string(raw, source=source).lower()
    if value not in VALID_MODES:
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"{source} must be one of: {', '.join(sorted(VALID_MODES))}",
            retryable=False,
        )
    return value


def _normalize_capabilities(raw: Any, *, source: str) -> Dict[str, bool]:
    payload = _require_object(raw, source=source)
    grants = {
        "can_patch": False,
        "can_block": False,
    }
    for key, value in payload.items():
        if key not in grants:
            continue
        if not isinstance(value, bool):
            raise MiddlewareError(
                500,
                "MODEIO_CONFIG_ERROR",
                f"{source}.{key} must be boolean",
                retryable=False,
            )
        grants[key] = value
    return grants


def _normalize_timeout_ms(raw: Any, *, source: str) -> Dict[str, int]:
    payload = _require_object(raw, source=source)
    timeout_ms: Dict[str, int] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not key.strip():
            raise MiddlewareError(
                500,
                "MODEIO_CONFIG_ERROR",
                f"{source} keys must be non-empty strings",
                retryable=False,
            )
        if not isinstance(value, int) or value <= 0:
            raise MiddlewareError(
                500,
                "MODEIO_CONFIG_ERROR",
                f"{source}.{key} must be a positive integer",
                retryable=False,
            )
        timeout_ms[key.strip()] = int(value)
    return timeout_ms


def _normalize_defaults(raw: Any, *, source: str) -> PluginHostDefaults:
    payload = _require_object(raw, source=source)
    pool_size_raw = payload.get("pool_size", 1)
    if not isinstance(pool_size_raw, int) or pool_size_raw <= 0:
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"{source}.pool_size must be a positive integer",
            retryable=False,
        )

    return PluginHostDefaults(
        mode=_normalize_mode(payload.get("mode"), source=f"{source}.mode"),
        capabilities_grant=_normalize_capabilities(
            payload.get("capabilities_grant"),
            source=f"{source}.capabilities_grant",
        ),
        pool_size=int(pool_size_raw),
        timeout_ms=_normalize_timeout_ms(
            payload.get("timeout_ms"),
            source=f"{source}.timeout_ms",
        ),
    )


def load_plugin_host_config(path: Path) -> PluginHostConfig:
    source = str(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"failed to read plugin host config: {source}",
            retryable=False,
        ) from error

    try:
        payload = json.loads(raw)
    except ValueError as error:
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"invalid JSON plugin host config: {source}",
            retryable=False,
        ) from error

    if not isinstance(payload, dict):
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"plugin host config root must be an object: {source}",
            retryable=False,
        )

    version = _require_string(payload.get("version"), source=f"{source}.version")
    if version != "1":
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            f"unsupported plugin host config version '{version}' in {source}",
            retryable=False,
        )

    runtime = _require_string(
        payload.get("runtime"), source=f"{source}.runtime"
    ).lower()
    working_directory = str(payload.get("working_directory", ".") or ".").strip() or "."

    return PluginHostConfig(
        version=version,
        runtime=runtime,
        command=_require_command(payload.get("command"), source=f"{source}.command"),
        working_directory=working_directory,
        defaults=_normalize_defaults(
            payload.get("defaults"), source=f"{source}.defaults"
        ),
        source_path=source,
    )


def resolve_plugin_host_command(
    host_config: PluginHostConfig, *, plugin_dir: Path
) -> List[str]:
    working_directory = Path(host_config.working_directory)
    if not working_directory.is_absolute():
        working_directory = (plugin_dir / working_directory).resolve()

    command: List[str] = []
    for item in host_config.command:
        candidate = Path(item)
        value = item
        if not candidate.is_absolute():
            resolved_candidate = (working_directory / candidate).resolve()
            if resolved_candidate.exists():
                value = str(resolved_candidate)
        command.append(value)
    return command
