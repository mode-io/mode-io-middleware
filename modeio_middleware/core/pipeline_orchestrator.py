#!/usr/bin/env python3

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from modeio_middleware.connectors.base import CanonicalInvocation
from modeio_middleware.core.pipeline_session import PipelineSession
from modeio_middleware.core.plugin_manager import ActivePlugin, PluginManager
from modeio_middleware.core.profiles import (
    resolve_plugin_error_policy,
    resolve_profile,
    resolve_profile_plugin_overrides,
    resolve_profile_plugins,
)


class PipelineOrchestrator:
    def __init__(self, *, config: Any, plugin_manager: PluginManager):
        self._config = config
        self._plugin_manager = plugin_manager

    def new_session(self, *, request_id: str) -> PipelineSession:
        return PipelineSession(
            request_id=request_id, profile=self._config.default_profile
        )

    def resolve_plugin_runtime(
        self,
        *,
        profile: str,
        on_plugin_error_override: Optional[str],
        plugin_overrides: Dict[str, Dict[str, Any]],
    ) -> Tuple[str, List[ActivePlugin]]:
        profile_config = resolve_profile(self._config.profiles or {}, profile)
        on_plugin_error = resolve_plugin_error_policy(
            profile_config, on_plugin_error_override
        )
        plugin_order = resolve_profile_plugins(profile_config)
        profile_overrides = resolve_profile_plugin_overrides(profile_config)
        active_plugins = self._plugin_manager.resolve_active_plugins(
            plugin_order,
            request_plugin_overrides=plugin_overrides,
            profile_plugin_overrides=profile_overrides,
        )
        return on_plugin_error, active_plugins

    def start_invocation(
        self, invocation: CanonicalInvocation
    ) -> Tuple[PipelineSession, str, Dict[str, Any]]:
        session = self.new_session(request_id=invocation.request_id)
        session.profile = invocation.profile
        on_plugin_error, session.active_plugins = self.resolve_plugin_runtime(
            profile=session.profile,
            on_plugin_error_override=invocation.on_plugin_error,
            plugin_overrides=invocation.plugin_overrides,
        )
        shared_state: Dict[str, Any] = {}
        return session, on_plugin_error, shared_state

    def _release_plugins(self, session: PipelineSession) -> None:
        if session.plugins_released:
            return
        self._plugin_manager.shutdown_active_plugins(session.active_plugins)
        session.plugins_released = True

    def shutdown_session_plugins(self, session: PipelineSession) -> None:
        self._release_plugins(session)

    def release_stream_plugins(self, session: PipelineSession) -> None:
        self._release_plugins(session)
