#!/usr/bin/env python3

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from modeio_middleware.core.engine import GatewayRuntimeConfig, MiddlewareEngine
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.plugin_overrides import validate_plugin_overrides
from modeio_middleware.plugin_catalog_discovery import build_plugin_catalog
from modeio_middleware.plugin_inventory import build_plugin_inventory_response
from modeio_middleware.runtime_config_store import (
    build_gateway_runtime_config_from_payload,
    is_runtime_config_writable,
    read_runtime_config_payload,
    write_runtime_config_payload,
)


@dataclass(frozen=True)
class RuntimeLaunchSettings:
    upstream_chat_completions_url: str
    upstream_responses_url: str
    upstream_timeout_seconds: int
    upstream_api_key_env: str
    default_profile: str


@dataclass
class PreparedEngineSwap:
    next_engine: MiddlewareEngine
    backup_path: str = ""


class EngineLease:
    def __init__(
        self, controller: "GatewayController", generation: int, engine: MiddlewareEngine
    ):
        self._controller = controller
        self._generation = generation
        self.engine = engine
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._controller.release_engine(self._generation)


class GatewayController:
    def __init__(self, runtime_config: GatewayRuntimeConfig):
        self._lock = threading.RLock()
        self._engine = MiddlewareEngine(runtime_config)
        self._request_journal = self._engine.services.request_journal
        self._generation = 1
        self._active_counts: Dict[int, int] = {self._generation: 0}
        self._retired: Dict[int, MiddlewareEngine] = {}
        self._launch_settings = RuntimeLaunchSettings(
            upstream_chat_completions_url=runtime_config.upstream_chat_completions_url,
            upstream_responses_url=runtime_config.upstream_responses_url,
            upstream_timeout_seconds=runtime_config.upstream_timeout_seconds,
            upstream_api_key_env=runtime_config.upstream_api_key_env,
            default_profile=runtime_config.default_profile,
        )
        self._config_path = (
            Path(runtime_config.config_path).expanduser()
            if runtime_config.config_path
            else None
        )

    def borrow_engine(self) -> EngineLease:
        with self._lock:
            generation = self._generation
            self._active_counts[generation] = self._active_counts.get(generation, 0) + 1
            return EngineLease(self, generation, self._engine)

    def release_engine(self, generation: int) -> None:
        retired_engine = None
        with self._lock:
            count = max(self._active_counts.get(generation, 0) - 1, 0)
            if count == 0:
                self._active_counts.pop(generation, None)
                retired_engine = self._retired.pop(generation, None)
            else:
                self._active_counts[generation] = count
        if retired_engine is not None:
            retired_engine.shutdown()

    def current_engine(self) -> MiddlewareEngine:
        with self._lock:
            return self._engine

    def current_generation(self) -> int:
        with self._lock:
            return self._generation

    def config_path(self) -> Optional[Path]:
        return self._config_path

    def config_writable(self) -> bool:
        return self._config_path is not None and is_runtime_config_writable(
            self._config_path
        )

    def request_journal(self):
        return self._request_journal

    def default_profile(self) -> str:
        return self._launch_settings.default_profile

    def process_http_request(self, **kwargs):
        lease = self.borrow_engine()
        try:
            return lease.engine.process_http_request(**kwargs)
        finally:
            lease.release()

    def process_models_request(self, **kwargs):
        lease = self.borrow_engine()
        try:
            return lease.engine.process_models_request(**kwargs)
        finally:
            lease.release()

    def monitoring_inventory(self) -> Dict[str, Any]:
        config_path = self._require_config_path()
        payload = read_runtime_config_payload(config_path)
        current_engine = self.current_engine()
        journal = self.request_journal()
        stats_snapshot = journal.stats_snapshot() if journal is not None else None
        return build_plugin_inventory_response(
            payload,
            config_file_path=config_path,
            preset_registry=current_engine.config.preset_registry or {},
            generation=self.current_generation(),
            default_profile=current_engine.config.default_profile,
            config_writable=self.config_writable(),
            stats_snapshot=stats_snapshot,
        )

    def _require_config_path(self) -> Path:
        if self._config_path is None:
            raise MiddlewareError(
                404,
                "MODEIO_PLUGIN_MANAGEMENT_UNAVAILABLE",
                "plugin management is unavailable for in-memory config",
                retryable=False,
            )
        return self._config_path

    def _validate_expected_generation(
        self, expected_generation: Optional[int]
    ) -> None:
        if expected_generation is None:
            return
        if expected_generation != self._generation:
            raise MiddlewareError(
                409,
                "MODEIO_GENERATION_CONFLICT",
                "plugin configuration is stale; refresh and try again",
                retryable=False,
                details={
                    "expectedGeneration": expected_generation,
                    "currentGeneration": self._generation,
                },
            )

    def _load_profile_update_payload(
        self,
        *,
        config_path: Path,
        profile_name: str,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        payload = read_runtime_config_payload(config_path)
        profiles = payload.get("profiles", {})
        if not isinstance(profiles, dict):
            raise MiddlewareError(
                500,
                "MODEIO_CONFIG_ERROR",
                "config.profiles must be an object",
                retryable=False,
            )
        if profile_name not in profiles or not isinstance(profiles[profile_name], dict):
            raise MiddlewareError(
                404,
                "MODEIO_PROFILE_NOT_FOUND",
                f"profile '{profile_name}' was not found",
                retryable=False,
            )
        return payload, profiles

    def _normalize_plugin_order(self, plugin_order: Any) -> list[str]:
        if not isinstance(plugin_order, list):
            raise MiddlewareError(
                400,
                "MODEIO_VALIDATION_ERROR",
                "field 'pluginOrder' must be an array",
                retryable=False,
            )

        normalized_order = []
        seen = set()
        for index, item in enumerate(plugin_order):
            if not isinstance(item, str) or not item.strip():
                raise MiddlewareError(
                    400,
                    "MODEIO_VALIDATION_ERROR",
                    f"pluginOrder[{index}] must be a non-empty string",
                    retryable=False,
                )
            name = item.strip()
            if name in seen:
                raise MiddlewareError(
                    400,
                    "MODEIO_VALIDATION_ERROR",
                    f"pluginOrder contains duplicate plugin '{name}'",
                    retryable=False,
                )
            seen.add(name)
            normalized_order.append(name)
        return normalized_order

    def _known_plugin_names(
        self, payload: Dict[str, Any], *, config_path: Path
    ) -> set[str]:
        catalog = build_plugin_catalog(payload, config_file_path=config_path)
        return set(catalog.entries.keys())

    def _validate_known_plugins(
        self,
        *,
        known_plugins: set[str],
        plugin_names: Any,
    ) -> None:
        for plugin_name in plugin_names:
            if plugin_name not in known_plugins:
                raise MiddlewareError(
                    400,
                    "MODEIO_VALIDATION_ERROR",
                    f"unknown plugin '{plugin_name}'",
                    retryable=False,
                )

    def _updated_profile_payload(
        self,
        profile_payload: Dict[str, Any],
        *,
        plugin_order: list[str],
        plugin_overrides: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        updated = dict(profile_payload)
        updated["plugins"] = list(plugin_order)
        updated["plugin_overrides"] = dict(plugin_overrides)
        return updated

    def _build_runtime_config_from_payload(self, payload: Dict[str, Any]):
        assert self._config_path is not None
        return build_gateway_runtime_config_from_payload(
            payload,
            config_path=self._config_path,
            upstream_chat_completions_url=self._launch_settings.upstream_chat_completions_url,
            upstream_responses_url=self._launch_settings.upstream_responses_url,
            upstream_timeout_seconds=self._launch_settings.upstream_timeout_seconds,
            upstream_api_key_env=self._launch_settings.upstream_api_key_env,
            default_profile=self._launch_settings.default_profile,
        )

    def _prepare_engine_swap(self, payload: Dict[str, Any]) -> PreparedEngineSwap:
        next_config = self._build_runtime_config_from_payload(payload)
        return PreparedEngineSwap(
            next_engine=MiddlewareEngine(
                next_config,
                request_journal=self._request_journal,
            )
        )

    def _activate_prepared_engine(self, prepared: PreparedEngineSwap) -> MiddlewareEngine | None:
        current_generation = self._generation
        current_engine = self._engine
        current_count = self._active_counts.get(current_generation, 0)

        self._generation = current_generation + 1
        self._engine = prepared.next_engine
        self._active_counts[self._generation] = 0

        if current_count == 0:
            self._active_counts.pop(current_generation, None)
            return current_engine

        self._retired[current_generation] = current_engine
        return None

    def update_profile_plugins(
        self,
        profile_name: str,
        *,
        plugin_order: Any,
        plugin_overrides: Any,
        expected_generation: Optional[int],
    ) -> Dict[str, Any]:
        config_path = self._require_config_path()
        if not self.config_writable():
            raise MiddlewareError(
                403,
                "MODEIO_CONFIG_READ_ONLY",
                "middleware config is not writable",
                retryable=False,
            )

        retired_engine = None
        backup_path = ""
        with self._lock:
            self._validate_expected_generation(expected_generation)
            payload, profiles = self._load_profile_update_payload(
                config_path=config_path,
                profile_name=profile_name,
            )
            normalized_order = self._normalize_plugin_order(plugin_order)

            validated_overrides = validate_plugin_overrides(
                plugin_overrides,
                path_prefix="pluginOverrides",
                object_error_message="field 'pluginOverrides' must be an object",
                error_status=400,
                error_code="MODEIO_VALIDATION_ERROR",
                allow_none=True,
            )

            known_plugins = self._known_plugin_names(
                payload,
                config_path=config_path,
            )
            self._validate_known_plugins(
                known_plugins=known_plugins,
                plugin_names=normalized_order,
            )
            self._validate_known_plugins(
                known_plugins=known_plugins,
                plugin_names=validated_overrides,
            )

            profiles[profile_name] = self._updated_profile_payload(
                profiles[profile_name],
                plugin_order=normalized_order,
                plugin_overrides=validated_overrides,
            )
            payload["profiles"] = profiles

            prepared = self._prepare_engine_swap(payload)
            try:
                prepared.backup_path = write_runtime_config_payload(config_path, payload)
            except Exception:
                prepared.next_engine.shutdown()
                raise

            backup_path = prepared.backup_path
            retired_engine = self._activate_prepared_engine(prepared)

        if retired_engine is not None:
            retired_engine.shutdown()

        return {
            "ok": True,
            "generation": self.current_generation(),
            "configPath": str(config_path),
            "backupPath": backup_path,
            "reloaded": True,
        }

    def shutdown(self) -> None:
        with self._lock:
            engines = [self._engine, *self._retired.values()]
            self._retired.clear()
            self._active_counts.clear()
        for engine in engines:
            try:
                engine.shutdown()
            except Exception:
                continue
