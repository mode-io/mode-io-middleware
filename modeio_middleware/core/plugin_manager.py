#!/usr/bin/env python3

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

from modeio_middleware.core.config_resolver import resolve_plugin_runtime_config
from modeio_middleware.core.contracts import (
    HOOK_ACTION_BLOCK,
    HOOK_ACTION_MODIFY,
    HOOK_ACTION_WARN,
)
from modeio_middleware.core.decision import normalize_decision_payload
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.hook_envelope import HookEnvelope
from modeio_middleware.core.payload_codec import (
    PayloadDenormalizationError,
    denormalize_request_payload,
    denormalize_response_payload,
    denormalize_stream_event_payload,
)
from modeio_middleware.core.payload_mutations import (
    SemanticMutationError,
    apply_semantic_operations,
)
from modeio_middleware.core.payload_types import NormalizedPayload
from modeio_middleware.registry.resolver import (
    MODE_ASSIST,
    MODE_OBSERVE,
    resolve_plugin_runtime_spec,
)
from modeio_middleware.runtime.base import PluginRuntime
from modeio_middleware.runtime.manager import PluginRuntimeLease, PluginRuntimeManager


@dataclass
class ActivePlugin:
    name: str
    runtime: PluginRuntime
    lease: Optional[PluginRuntimeLease]
    config: Dict[str, Any]
    mode: str
    capabilities: Dict[str, bool]
    supported_hooks: List[str]


@dataclass
class HookPipelineResult:
    body: Dict[str, Any]
    headers: Dict[str, str]
    normalized_payload: Dict[str, Any] = field(default_factory=dict)
    actions: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    degraded: List[str] = field(default_factory=list)
    blocked: bool = False
    block_message: str = ""


@dataclass
class StreamEventPipelineResult:
    event: Dict[str, Any]
    normalized_payload: Dict[str, Any] = field(default_factory=dict)
    actions: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)
    degraded: List[str] = field(default_factory=list)
    blocked: bool = False
    block_message: str = ""


def _normalize_header_map(raw: Dict[str, Any]) -> Dict[str, str]:
    normalized_headers: Dict[str, str] = {}
    for key, value in raw.items():
        normalized_headers[str(key)] = str(value)
    return normalized_headers


class PluginManager:
    def __init__(
        self,
        plugins_config: Dict[str, Any],
        preset_registry: Optional[Dict[str, Any]] = None,
        config_base_dir: Optional[str] = None,
        runtime_manager: Optional[PluginRuntimeManager] = None,
    ):
        if not isinstance(plugins_config, dict):
            raise MiddlewareError(
                500,
                "MODEIO_CONFIG_ERROR",
                "plugins config must be an object",
            )
        self._plugins_config = plugins_config
        self._preset_registry = preset_registry or {}
        if isinstance(config_base_dir, str) and config_base_dir.strip():
            self._config_base_dir = Path(config_base_dir.strip())
        else:
            self._config_base_dir = Path.cwd()
        self._runtime_manager = runtime_manager or PluginRuntimeManager()

    def resolve_active_plugins(
        self,
        plugin_order: Iterable[str],
        request_plugin_overrides: Dict[str, Dict[str, Any]],
        profile_plugin_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[ActivePlugin]:
        profile_overrides = profile_plugin_overrides or {}
        active: List[ActivePlugin] = []
        try:
            for plugin_name in plugin_order:
                plugin_config = self._plugins_config.get(plugin_name)
                request_override = request_plugin_overrides.get(plugin_name, {})
                if not isinstance(request_override, dict):
                    raise MiddlewareError(
                        400,
                        "MODEIO_VALIDATION_ERROR",
                        f"modeio.plugins.{plugin_name} must be an object",
                    )

                profile_override = profile_overrides.get(plugin_name, {})
                if not isinstance(profile_override, dict):
                    raise MiddlewareError(
                        500,
                        "MODEIO_CONFIG_ERROR",
                        f"profile.plugin_overrides.{plugin_name} must be an object",
                        retryable=False,
                    )

                resolved = resolve_plugin_runtime_config(
                    plugin_name=plugin_name,
                    plugin_config=plugin_config,
                    preset_registry=self._preset_registry,
                    profile_override=profile_override,
                    request_override=request_override,
                )

                if not resolved.enabled:
                    continue

                spec = resolve_plugin_runtime_spec(
                    resolved=resolved,
                    config_base_dir=self._config_base_dir,
                )
                lease = self._runtime_manager.acquire(spec)
                active.append(
                    ActivePlugin(
                        name=plugin_name,
                        runtime=lease.runtime,
                        lease=lease,
                        config=spec.hook_config,
                        mode=spec.mode,
                        capabilities=spec.capabilities,
                        supported_hooks=spec.supported_hooks,
                    )
                )
        except Exception:
            self.shutdown_active_plugins(active)
            raise
        return active

    def shutdown_active_plugins(self, active_plugins: Iterable[ActivePlugin]) -> None:
        for active in active_plugins:
            lease = getattr(active, "lease", None)
            if lease is None:
                continue
            try:
                lease.release()
            finally:
                active.lease = None

    def shutdown(self) -> None:
        self._runtime_manager.shutdown()

    def _apply_action_controls(
        self,
        *,
        active: ActivePlugin,
        action: str,
        result: Any,
        connector_capabilities: Optional[Dict[str, bool]],
    ) -> str:
        original_action = action
        effective_action = action

        can_patch = bool(active.capabilities.get("can_patch", False))
        can_block = bool(active.capabilities.get("can_block", False))

        if effective_action == HOOK_ACTION_MODIFY and not can_patch:
            effective_action = HOOK_ACTION_WARN
        elif effective_action == HOOK_ACTION_BLOCK and not can_block:
            effective_action = HOOK_ACTION_WARN

        if isinstance(connector_capabilities, dict):
            connector_can_patch = bool(connector_capabilities.get("can_patch", True))
            connector_can_block = bool(connector_capabilities.get("can_block", True))

            if effective_action == HOOK_ACTION_MODIFY and not connector_can_patch:
                effective_action = HOOK_ACTION_WARN
            elif effective_action == HOOK_ACTION_BLOCK and not connector_can_block:
                effective_action = HOOK_ACTION_WARN

        if active.mode == MODE_OBSERVE and effective_action in {
            HOOK_ACTION_MODIFY,
            HOOK_ACTION_BLOCK,
        }:
            effective_action = HOOK_ACTION_WARN
        elif active.mode == MODE_ASSIST and effective_action == HOOK_ACTION_BLOCK:
            effective_action = HOOK_ACTION_WARN

        if effective_action != original_action:
            result.degraded.append(
                f"action_downgraded:{active.name}:{original_action}->{effective_action}:{active.mode}"
            )

        return effective_action

    def _normalize_hook_result(self, payload: Any) -> Dict[str, Any]:
        return normalize_decision_payload(payload, stream=False)

    def _normalize_stream_hook_result(self, payload: Any) -> Dict[str, Any]:
        return normalize_decision_payload(payload, stream=True)

    def _extract_connector_metadata(
        self,
        *,
        context: Optional[Dict[str, Any]],
        request_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        source_context: Optional[Dict[str, Any]] = None
        if isinstance(context, dict):
            source_context = context
        elif isinstance(request_context, dict):
            source_context = request_context

        if source_context is None:
            return {}

        metadata: Dict[str, Any] = {}
        for key in ("source", "source_event", "surface_capabilities", "native_event"):
            if key in source_context:
                metadata[key] = source_context[key]
        return metadata

    def _build_hook_input(
        self,
        *,
        active: ActivePlugin,
        request_id: str,
        endpoint_kind: str,
        profile: str,
        shared_state: Dict[str, Any],
        services: Optional[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        request_context: Optional[Dict[str, Any]] = None,
        response_context: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        native: Optional[Dict[str, Any]] = None,
        request_body: Optional[Dict[str, Any]] = None,
        request_headers: Optional[Dict[str, str]] = None,
        response_body: Optional[Dict[str, Any]] = None,
        response_headers: Optional[Dict[str, str]] = None,
        event: Optional[Dict[str, Any]] = None,
    ) -> HookEnvelope:
        plugin_state = shared_state.setdefault(active.name, {})
        connector_metadata = self._extract_connector_metadata(
            context=context,
            request_context=request_context,
        )
        return HookEnvelope(
            request_id=request_id,
            endpoint_kind=endpoint_kind,
            profile=profile,
            plugin_config=active.config,
            shared_state=shared_state,
            plugin_state=plugin_state,
            services=services or {},
            context=context,
            request_context=request_context,
            response_context=response_context,
            payload=payload,
            native=native,
            request_body=request_body,
            request_headers=request_headers,
            response_body=response_body,
            response_headers=response_headers,
            event=event,
            source=connector_metadata.get("source"),
            source_event=connector_metadata.get("source_event"),
            surface_capabilities=connector_metadata.get("surface_capabilities"),
            native_event=connector_metadata.get("native_event"),
        )

    def _record_telemetry(
        self,
        services: Optional[Dict[str, Any]],
        *,
        request_id: str,
        plugin_name: str,
        hook_name: str,
        action: str,
        duration_ms: float,
        errored: bool,
        reported_action: str | None = None,
        error_type: str | None = None,
    ) -> None:
        if not isinstance(services, dict):
            return
        telemetry = services.get("telemetry")
        if telemetry is not None:
            record = getattr(telemetry, "record", None)
            if callable(record):
                record(
                    plugin_name=plugin_name,
                    hook_name=hook_name,
                    action=action,
                    duration_ms=duration_ms,
                    errored=errored,
                )

        request_journal = services.get("request_journal")
        if request_journal is None:
            return
        record_hook = getattr(request_journal, "record_hook_execution", None)
        if not callable(record_hook):
            return
        record_hook(
            request_id=request_id,
            plugin_name=plugin_name,
            hook_name=hook_name,
            effective_action=action,
            duration_ms=duration_ms,
            errored=errored,
            reported_action=reported_action,
            error_type=error_type,
        )

    def _handle_plugin_error(
        self,
        *,
        plugin_name: str,
        error: Exception,
        on_plugin_error: str,
        result: Any,
    ) -> None:
        reason = f"plugin_error:{plugin_name}"
        result.degraded.append(reason)
        result.actions.append(f"{plugin_name}:error")

        if on_plugin_error == "fail_safe":
            result.blocked = True
            result.block_message = (
                f"plugin '{plugin_name}' failed: {type(error).__name__}"
            )
            return

        severity = "medium" if on_plugin_error == "warn" else "low"
        result.findings.append(
            {
                "class": "plugin_error",
                "severity": severity,
                "confidence": 1.0,
                "reason": f"plugin '{plugin_name}' failed",
                "evidence": [
                    type(error).__name__,
                    *([str(error)] if str(error) else []),
                ],
            }
        )

    def _iter_supported_plugins(
        self,
        active_plugins: Iterable[ActivePlugin],
        *,
        hook_name: str,
        reverse: bool = False,
    ) -> Iterator[ActivePlugin]:
        plugins = list(active_plugins)
        if reverse:
            plugins.reverse()
        for active in plugins:
            if hook_name in active.supported_hooks:
                yield active

    def _invoke_hook(
        self,
        *,
        active: ActivePlugin,
        hook_name: str,
        hook_input: HookEnvelope,
        normalize_hook_result: Callable[[Any], Dict[str, Any]],
        result: Any,
        request_id: str,
        on_plugin_error: str,
        services: Optional[Dict[str, Any]],
        connector_capabilities: Optional[Dict[str, bool]],
    ) -> tuple[str, Dict[str, Any]] | None:
        start = time.perf_counter()
        try:
            payload = active.runtime.invoke(hook_name, hook_input)
            normalized = normalize_hook_result(payload)
        except Exception as error:
            duration_ms = (time.perf_counter() - start) * 1000
            self._record_telemetry(
                services,
                request_id=request_id,
                plugin_name=active.name,
                hook_name=hook_name,
                action="error",
                duration_ms=duration_ms,
                errored=True,
                error_type=type(error).__name__,
            )
            self._handle_plugin_error(
                plugin_name=active.name,
                error=error,
                on_plugin_error=on_plugin_error,
                result=result,
            )
            return None

        action = self._apply_action_controls(
            active=active,
            action=normalized["action"],
            result=result,
            connector_capabilities=connector_capabilities,
        )
        duration_ms = (time.perf_counter() - start) * 1000
        self._record_telemetry(
            services,
            request_id=request_id,
            plugin_name=active.name,
            hook_name=hook_name,
            action=action,
            duration_ms=duration_ms,
            errored=False,
            reported_action=normalized["action"],
        )
        result.actions.append(f"{active.name}:{action}")
        result.findings.extend(normalized["findings"])
        return action, normalized

    def _run_hook_pipeline(
        self,
        active_plugins: Iterable[ActivePlugin],
        *,
        hook_name: str,
        reverse: bool,
        request_id: str,
        on_plugin_error: str,
        services: Optional[Dict[str, Any]],
        connector_capabilities: Optional[Dict[str, bool]],
        result: Any,
        build_hook_input: Callable[[ActivePlugin], HookEnvelope],
        normalize_hook_result: Callable[[Any], Dict[str, Any]],
        blocked_message_suffix: str,
        apply_modifications: Optional[
            Callable[[str, Any, Dict[str, Any]], None]
        ] = None,
    ) -> Any:
        for active in self._iter_supported_plugins(
            active_plugins, hook_name=hook_name, reverse=reverse
        ):
            hook_input = build_hook_input(active)
            invocation = self._invoke_hook(
                active=active,
                hook_name=hook_name,
                hook_input=hook_input,
                normalize_hook_result=normalize_hook_result,
                result=result,
                request_id=request_id,
                on_plugin_error=on_plugin_error,
                services=services,
                connector_capabilities=connector_capabilities,
            )
            if invocation is None:
                if result.blocked:
                    return result
                continue

            action, normalized = invocation
            if action == HOOK_ACTION_MODIFY and apply_modifications is not None:
                apply_modifications(active.name, result, normalized)
            if action == HOOK_ACTION_BLOCK:
                result.blocked = True
                result.block_message = (
                    normalized.get("message")
                    or f"plugin '{active.name}' blocked {blocked_message_suffix}"
                )
                return result

        return result

    def _mutate_payload(
        self,
        *,
        plugin_name: str,
        result: HookPipelineResult | StreamEventPipelineResult,
        normalized: Dict[str, Any],
        phase: str,
    ) -> None:
        operations = normalized.get("operations") or []
        if not operations:
            return

        try:
            current_payload = NormalizedPayload.from_public_dict(
                result.normalized_payload
            )
            updated_payload = apply_semantic_operations(current_payload, operations)
            if phase == "request":
                result.body = denormalize_request_payload(updated_payload)
            elif phase == "response":
                result.body = denormalize_response_payload(updated_payload)
            elif phase == "stream_event":
                result.event = denormalize_stream_event_payload(updated_payload)
            else:
                raise SemanticMutationError(
                    f"unsupported payload mutation phase '{phase}'"
                )
            result.normalized_payload = updated_payload.to_public_dict()
        except (SemanticMutationError, PayloadDenormalizationError) as error:
            result.degraded.append(
                f"semantic_mutation_failed:{plugin_name}:{type(error).__name__}"
            )
            result.findings.append(
                {
                    "class": "semantic_mutation_failed",
                    "severity": "medium",
                    "confidence": 1.0,
                    "reason": f"plugin '{plugin_name}' returned an unsupported semantic rewrite",
                    "evidence": [str(error)],
                }
            )

    def _apply_request_modifications(
        self,
        plugin_name: str,
        result: HookPipelineResult,
        normalized: Dict[str, Any],
    ) -> None:
        self._mutate_payload(
            plugin_name=plugin_name,
            result=result,
            normalized=normalized,
            phase="request",
        )

    def _apply_response_modifications(
        self,
        plugin_name: str,
        result: HookPipelineResult,
        normalized: Dict[str, Any],
    ) -> None:
        self._mutate_payload(
            plugin_name=plugin_name,
            result=result,
            normalized=normalized,
            phase="response",
        )

    def _apply_stream_event_modifications(
        self,
        plugin_name: str,
        result: StreamEventPipelineResult,
        normalized: Dict[str, Any],
    ) -> None:
        self._mutate_payload(
            plugin_name=plugin_name,
            result=result,
            normalized=normalized,
            phase="stream_event",
        )

    def _apply_stream_lifecycle_hook(
        self,
        active_plugins: Iterable[ActivePlugin],
        *,
        request_id: str,
        endpoint_kind: str,
        profile: str,
        request_context: Dict[str, Any],
        response_context: Optional[Dict[str, Any]],
        shared_state: Dict[str, Any],
        on_plugin_error: str,
        services: Optional[Dict[str, Any]],
        hook_name: str,
        blocked_message_suffix: str,
        connector_capabilities: Optional[Dict[str, bool]],
    ) -> HookPipelineResult:
        result = HookPipelineResult(body={}, headers={})

        def build_hook_input(active: ActivePlugin) -> HookEnvelope:
            return self._build_hook_input(
                active=active,
                request_id=request_id,
                endpoint_kind=endpoint_kind,
                profile=profile,
                shared_state=shared_state,
                services=services,
                request_context=request_context,
                response_context=response_context,
            )

        return self._run_hook_pipeline(
            active_plugins,
            hook_name=hook_name,
            reverse=True,
            request_id=request_id,
            on_plugin_error=on_plugin_error,
            services=services,
            connector_capabilities=connector_capabilities,
            result=result,
            build_hook_input=build_hook_input,
            normalize_hook_result=self._normalize_stream_hook_result,
            blocked_message_suffix=blocked_message_suffix,
        )

    def apply_pre_request(
        self,
        active_plugins: Iterable[ActivePlugin],
        *,
        request_id: str,
        endpoint_kind: str,
        profile: str,
        request_body: Dict[str, Any],
        normalized_payload: Dict[str, Any],
        native_payload: Dict[str, Any],
        request_headers: Dict[str, str],
        context: Dict[str, Any],
        shared_state: Dict[str, Any],
        on_plugin_error: str,
        services: Optional[Dict[str, Any]] = None,
        connector_capabilities: Optional[Dict[str, bool]] = None,
    ) -> HookPipelineResult:
        result = HookPipelineResult(
            body=copy.deepcopy(request_body),
            headers=dict(request_headers),
            normalized_payload=copy.deepcopy(normalized_payload),
        )

        def build_hook_input(active: ActivePlugin) -> HookEnvelope:
            return self._build_hook_input(
                active=active,
                request_id=request_id,
                endpoint_kind=endpoint_kind,
                profile=profile,
                shared_state=shared_state,
                services=services,
                context=context,
                payload=result.normalized_payload,
                native=native_payload,
                request_body=result.body,
                request_headers=result.headers,
            )

        return self._run_hook_pipeline(
            active_plugins,
            hook_name="pre_request",
            reverse=False,
            request_id=request_id,
            on_plugin_error=on_plugin_error,
            services=services,
            connector_capabilities=connector_capabilities,
            result=result,
            build_hook_input=build_hook_input,
            normalize_hook_result=self._normalize_hook_result,
            blocked_message_suffix="request",
            apply_modifications=self._apply_request_modifications,
        )

    def apply_post_response(
        self,
        active_plugins: Iterable[ActivePlugin],
        *,
        request_id: str,
        endpoint_kind: str,
        profile: str,
        request_context: Dict[str, Any],
        response_body: Dict[str, Any],
        normalized_payload: Dict[str, Any],
        native_payload: Dict[str, Any],
        response_headers: Dict[str, str],
        shared_state: Dict[str, Any],
        on_plugin_error: str,
        services: Optional[Dict[str, Any]] = None,
        connector_capabilities: Optional[Dict[str, bool]] = None,
    ) -> HookPipelineResult:
        result = HookPipelineResult(
            body=copy.deepcopy(response_body),
            headers=dict(response_headers),
            normalized_payload=copy.deepcopy(normalized_payload),
        )

        def build_hook_input(active: ActivePlugin) -> HookEnvelope:
            return self._build_hook_input(
                active=active,
                request_id=request_id,
                endpoint_kind=endpoint_kind,
                profile=profile,
                shared_state=shared_state,
                services=services,
                request_context=request_context,
                payload=result.normalized_payload,
                native=native_payload,
                response_body=result.body,
                response_headers=result.headers,
            )

        return self._run_hook_pipeline(
            active_plugins,
            hook_name="post_response",
            reverse=True,
            request_id=request_id,
            on_plugin_error=on_plugin_error,
            services=services,
            connector_capabilities=connector_capabilities,
            result=result,
            build_hook_input=build_hook_input,
            normalize_hook_result=self._normalize_hook_result,
            blocked_message_suffix="response",
            apply_modifications=self._apply_response_modifications,
        )

    def apply_post_stream_start(
        self,
        active_plugins: Iterable[ActivePlugin],
        *,
        request_id: str,
        endpoint_kind: str,
        profile: str,
        request_context: Dict[str, Any],
        response_context: Dict[str, Any],
        shared_state: Dict[str, Any],
        on_plugin_error: str,
        services: Optional[Dict[str, Any]] = None,
        connector_capabilities: Optional[Dict[str, bool]] = None,
    ) -> HookPipelineResult:
        return self._apply_stream_lifecycle_hook(
            active_plugins,
            request_id=request_id,
            endpoint_kind=endpoint_kind,
            profile=profile,
            request_context=request_context,
            response_context=response_context,
            shared_state=shared_state,
            on_plugin_error=on_plugin_error,
            services=services,
            hook_name="post_stream_start",
            blocked_message_suffix="stream",
            connector_capabilities=connector_capabilities,
        )

    def apply_post_stream_event(
        self,
        active_plugins: Iterable[ActivePlugin],
        *,
        request_id: str,
        endpoint_kind: str,
        profile: str,
        request_context: Dict[str, Any],
        event: Dict[str, Any],
        normalized_payload: Dict[str, Any],
        native_payload: Dict[str, Any],
        shared_state: Dict[str, Any],
        on_plugin_error: str,
        services: Optional[Dict[str, Any]] = None,
        connector_capabilities: Optional[Dict[str, bool]] = None,
    ) -> StreamEventPipelineResult:
        result = StreamEventPipelineResult(
            event=copy.deepcopy(event),
            normalized_payload=copy.deepcopy(normalized_payload),
        )

        def build_hook_input(active: ActivePlugin) -> HookEnvelope:
            return self._build_hook_input(
                active=active,
                request_id=request_id,
                endpoint_kind=endpoint_kind,
                profile=profile,
                shared_state=shared_state,
                services=services,
                request_context=request_context,
                payload=result.normalized_payload,
                native=native_payload,
                event=result.event,
            )

        return self._run_hook_pipeline(
            active_plugins,
            hook_name="post_stream_event",
            reverse=True,
            request_id=request_id,
            on_plugin_error=on_plugin_error,
            services=services,
            connector_capabilities=connector_capabilities,
            result=result,
            build_hook_input=build_hook_input,
            normalize_hook_result=self._normalize_stream_hook_result,
            blocked_message_suffix="stream event",
            apply_modifications=self._apply_stream_event_modifications,
        )

    def apply_post_stream_end(
        self,
        active_plugins: Iterable[ActivePlugin],
        *,
        request_id: str,
        endpoint_kind: str,
        profile: str,
        request_context: Dict[str, Any],
        shared_state: Dict[str, Any],
        on_plugin_error: str,
        services: Optional[Dict[str, Any]] = None,
        connector_capabilities: Optional[Dict[str, bool]] = None,
    ) -> HookPipelineResult:
        return self._apply_stream_lifecycle_hook(
            active_plugins,
            request_id=request_id,
            endpoint_kind=endpoint_kind,
            profile=profile,
            request_context=request_context,
            response_context=None,
            shared_state=shared_state,
            on_plugin_error=on_plugin_error,
            services=services,
            hook_name="post_stream_end",
            blocked_message_suffix="stream end",
            connector_capabilities=connector_capabilities,
        )
