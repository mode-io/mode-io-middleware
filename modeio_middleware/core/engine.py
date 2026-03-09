#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Union

from modeio_middleware.connectors.base import CanonicalInvocation, ConnectorAdapter
from modeio_middleware.connectors.claude_hooks import (
    CLAUDE_HOOK_CONNECTOR_PATH,
    ClaudeHookConnector,
    build_claude_hook_response,
)
from modeio_middleware.connectors.openai_http import OpenAIHttpConnector
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.http_contract import contract_headers, error_payload
from modeio_middleware.core.observability.service import build_request_journal_service
from modeio_middleware.core.pipeline_session import PipelineSession
from modeio_middleware.core.plugin_manager import ActivePlugin, PluginManager
from modeio_middleware.core.profiles import (
    DEFAULT_PROFILE,
    resolve_plugin_error_policy,
    resolve_profile,
    resolve_profile_plugin_overrides,
    resolve_profile_plugins,
)
from modeio_middleware.core.services.engine_services import EngineServices
from modeio_middleware.core.services.telemetry import PluginTelemetry
from modeio_middleware.core.stream_relay import iter_transformed_sse_stream
from modeio_middleware.core.upstream_client import (
    forward_upstream_json,
    forward_upstream_stream,
)


@dataclass(frozen=True)
class GatewayRuntimeConfig:
    upstream_chat_completions_url: str
    upstream_responses_url: str
    upstream_timeout_seconds: int
    upstream_api_key_env: str
    default_profile: str = DEFAULT_PROFILE
    profiles: Dict[str, Any] = None  # type: ignore[assignment]
    plugins: Dict[str, Any] = None  # type: ignore[assignment]
    preset_registry: Dict[str, Any] = None  # type: ignore[assignment]
    service_config: Dict[str, Any] = None  # type: ignore[assignment]
    config_base_dir: str = ""
    config_path: str = ""


@dataclass
class ProcessResult:
    status: int
    payload: Dict[str, Any]
    headers: Dict[str, str]


@dataclass
class StreamProcessResult:
    status: int
    headers: Dict[str, str]
    stream: Optional[Iterable[bytes]] = None
    payload: Optional[Dict[str, Any]] = None


def _build_runtime_services(service_config: Optional[Dict[str, Any]]) -> EngineServices:
    try:
        request_journal = build_request_journal_service(service_config)
    except ValueError as error:
        raise MiddlewareError(
            500,
            "MODEIO_CONFIG_ERROR",
            str(error),
            retryable=False,
        ) from error
    return EngineServices(
        telemetry=PluginTelemetry(),
        request_journal=request_journal,
    )


class MiddlewareEngine:
    def __init__(self, runtime_config: GatewayRuntimeConfig):
        self.config = runtime_config
        self.plugin_manager = PluginManager(
            runtime_config.plugins or {},
            preset_registry=runtime_config.preset_registry or {},
            config_base_dir=runtime_config.config_base_dir,
        )
        self.services = _build_runtime_services(runtime_config.service_config)
        self._plugin_services = self.services.as_plugin_services()
        self._connectors: tuple[ConnectorAdapter, ...] = (
            ClaudeHookConnector(),
            OpenAIHttpConnector(),
        )

    def _journal_start(self, invocation: CanonicalInvocation) -> None:
        journal = self.services.request_journal
        if journal is None:
            return
        journal.start_request(
            request_id=invocation.request_id,
            source=invocation.source,
            client_name=invocation.client_name,
            source_event=invocation.source_event,
            endpoint_kind=invocation.endpoint_kind,
            phase=invocation.phase,
            profile=invocation.profile,
            stream=invocation.stream,
            request_body=invocation.request_body or None,
            response_body=invocation.response_body or None,
        )

    def _journal_finish_error(self, request_id: str, error: MiddlewareError) -> None:
        journal = self.services.request_journal
        if journal is None:
            return
        blocked = error.code == "MODEIO_PLUGIN_BLOCKED"
        journal.finish_error(
            request_id=request_id,
            error_code=error.code,
            error_message=error.message,
            blocked=blocked,
            block_message=error.message if blocked else None,
        )

    def _resolve_plugin_runtime(
        self,
        *,
        profile: str,
        on_plugin_error_override: Optional[str],
        plugin_overrides: Dict[str, Dict[str, Any]],
    ) -> tuple[str, List[ActivePlugin]]:
        profile_config = resolve_profile(self.config.profiles or {}, profile)
        on_plugin_error = resolve_plugin_error_policy(
            profile_config, on_plugin_error_override
        )
        plugin_order = resolve_profile_plugins(profile_config)
        profile_overrides = resolve_profile_plugin_overrides(profile_config)
        active_plugins = self.plugin_manager.resolve_active_plugins(
            plugin_order,
            request_plugin_overrides=plugin_overrides,
            profile_plugin_overrides=profile_overrides,
        )
        return on_plugin_error, active_plugins

    def _resolve_connector(self, path: str) -> ConnectorAdapter:
        for connector in self._connectors:
            if connector.matches(path):
                return connector
        raise MiddlewareError(
            404,
            "MODEIO_ROUTE_NOT_FOUND",
            "route not found",
            retryable=False,
        )

    def _new_session(self, *, request_id: str) -> PipelineSession:
        return PipelineSession(
            request_id=request_id, profile=self.config.default_profile
        )

    def _session_headers(self, session: PipelineSession) -> Dict[str, str]:
        return contract_headers(
            session.request_id,
            profile=session.profile,
            pre_actions=session.pre_actions,
            post_actions=session.post_actions,
            degraded=session.degraded,
            upstream_called=session.upstream_called,
        )

    def _error_process_result(
        self, session: PipelineSession, error: MiddlewareError
    ) -> ProcessResult:
        payload = error_payload(
            session.request_id,
            error.code,
            error.message,
            retryable=error.retryable,
            details=error.details,
        )
        headers = self._session_headers(session)
        return ProcessResult(status=error.status, payload=payload, headers=headers)

    def _shutdown_session_plugins(self, session: PipelineSession) -> None:
        if session.plugins_released:
            return
        self.plugin_manager.shutdown_active_plugins(session.active_plugins)
        session.plugins_released = True

    def _build_request_context(self, invocation: CanonicalInvocation) -> Dict[str, Any]:
        return {
            "endpoint_kind": invocation.endpoint_kind,
            "default_profile": self.config.default_profile,
            "upstream_chat_completions_url": self.config.upstream_chat_completions_url,
            "upstream_responses_url": self.config.upstream_responses_url,
            "client_name": invocation.client_name,
            **invocation.connector_context,
        }

    def _start_invocation(
        self,
        invocation: CanonicalInvocation,
    ) -> tuple[PipelineSession, str, Dict[str, Any], Dict[str, Any]]:
        session = self._new_session(request_id=invocation.request_id)
        session.profile = invocation.profile
        on_plugin_error, session.active_plugins = self._resolve_plugin_runtime(
            profile=session.profile,
            on_plugin_error_override=invocation.on_plugin_error,
            plugin_overrides=invocation.plugin_overrides,
        )
        shared_state: Dict[str, Any] = {}
        request_context = self._build_request_context(invocation)
        return session, on_plugin_error, shared_state, request_context

    def _release_stream_plugins(self, session: PipelineSession) -> None:
        if session.plugins_released:
            return
        self.plugin_manager.shutdown_active_plugins(session.active_plugins)
        session.plugins_released = True

    def shutdown(self) -> None:
        self.plugin_manager.shutdown()

    def process_http_request(
        self,
        *,
        path: str,
        request_id: str,
        payload: Dict[str, Any],
        incoming_headers: Dict[str, str],
    ) -> Union[ProcessResult, StreamProcessResult]:
        try:
            connector = self._resolve_connector(path)
            invocation = connector.parse(
                request_id=request_id,
                payload=payload,
                incoming_headers=incoming_headers,
                default_profile=self.config.default_profile,
                path=path,
            )
            self._journal_start(invocation)
        except MiddlewareError as error:
            session = self._new_session(request_id=request_id)
            return self._error_process_result(session, error)

        if invocation.phase == "request":
            return self.process_openai_invocation(invocation)
        return self._process_connector_hook(invocation)

    def process_request(
        self,
        *,
        endpoint_kind: str,
        request_id: str,
        request_body: Dict[str, Any],
        incoming_headers: Dict[str, str],
    ) -> Union[ProcessResult, StreamProcessResult]:
        path = (
            "/v1/chat/completions"
            if endpoint_kind == "chat_completions"
            else "/v1/responses"
        )
        return self.process_http_request(
            path=path,
            request_id=request_id,
            payload=request_body,
            incoming_headers=incoming_headers,
        )

    def process_openai_invocation(
        self,
        invocation: CanonicalInvocation,
    ) -> Union[ProcessResult, StreamProcessResult]:
        session, on_plugin_error, shared_state, request_context = (
            self._start_invocation(invocation)
        )
        connector_capabilities = invocation.connector_capabilities.as_dict()
        journal = self.services.request_journal
        streaming_response = False

        try:
            pre_result = self.plugin_manager.apply_pre_request(
                session.active_plugins,
                request_id=session.request_id,
                endpoint_kind=invocation.endpoint_kind,
                profile=session.profile,
                request_body=invocation.request_body,
                request_headers=invocation.incoming_headers,
                context=request_context,
                shared_state=shared_state,
                on_plugin_error=on_plugin_error,
                services=self._plugin_services,
                connector_capabilities=connector_capabilities,
            )
            session.pre_actions = pre_result.actions
            session.degraded.extend(pre_result.degraded)
            if journal is not None:
                journal.record_pre_result(
                    request_id=session.request_id,
                    effective_request_body=pre_result.body,
                    pre_actions=list(pre_result.actions),
                    degraded=list(pre_result.degraded),
                    findings=list(pre_result.findings),
                    blocked=pre_result.blocked,
                    block_message=pre_result.block_message,
                )
            if pre_result.blocked:
                raise MiddlewareError(
                    403,
                    "MODEIO_PLUGIN_BLOCKED",
                    pre_result.block_message,
                    retryable=False,
                    details={"phase": "pre_request"},
                )

            response_request_context = {
                **request_context,
                "preFindings": pre_result.findings,
            }
            if invocation.stream:
                stream_result = self._process_stream_request(
                    endpoint_kind=invocation.endpoint_kind,
                    session=session,
                    on_plugin_error=on_plugin_error,
                    shared_state=shared_state,
                    request_context=response_request_context,
                    upstream_payload=pre_result.body,
                    upstream_headers=pre_result.headers,
                    connector_capabilities=connector_capabilities,
                )
                streaming_response = isinstance(stream_result, StreamProcessResult)
                return stream_result

            if journal is not None:
                journal.mark_upstream_start(request_id=session.request_id)
            session.upstream_called = True
            upstream_payload = forward_upstream_json(
                config=self.config,
                endpoint_kind=invocation.endpoint_kind,
                payload=pre_result.body,
                incoming_headers=pre_result.headers,
            )
            if journal is not None:
                journal.record_upstream_result(
                    request_id=session.request_id,
                    response_body=upstream_payload,
                )

            post_result = self.plugin_manager.apply_post_response(
                session.active_plugins,
                request_id=session.request_id,
                endpoint_kind=invocation.endpoint_kind,
                profile=session.profile,
                request_context=response_request_context,
                response_body=upstream_payload,
                response_headers={},
                shared_state=shared_state,
                on_plugin_error=on_plugin_error,
                services=self._plugin_services,
                connector_capabilities=connector_capabilities,
            )
            session.post_actions = post_result.actions
            session.degraded.extend(post_result.degraded)
            if journal is not None:
                journal.record_post_result(
                    request_id=session.request_id,
                    effective_response_body=post_result.body,
                    post_actions=list(post_result.actions),
                    degraded=list(post_result.degraded),
                    findings=list(post_result.findings),
                    blocked=post_result.blocked,
                    block_message=post_result.block_message,
                )
            if post_result.blocked:
                raise MiddlewareError(
                    403,
                    "MODEIO_PLUGIN_BLOCKED",
                    post_result.block_message,
                    retryable=False,
                    details={"phase": "post_response"},
                )

            headers = self._session_headers(session)
            if journal is not None:
                journal.finish_success(request_id=session.request_id)
            return ProcessResult(status=200, payload=post_result.body, headers=headers)

        except MiddlewareError as error:
            if journal is not None:
                self._journal_finish_error(session.request_id, error)
            return self._error_process_result(session, error)
        except Exception:
            error = MiddlewareError(
                503,
                "MODEIO_INTERNAL_ERROR",
                "unexpected internal error",
                retryable=False,
            )
            if journal is not None:
                self._journal_finish_error(session.request_id, error)
            return self._error_process_result(session, error)
        finally:
            if not streaming_response:
                self._shutdown_session_plugins(session)

    def process_claude_hook(
        self,
        *,
        request_id: str,
        payload: Dict[str, Any],
        incoming_headers: Dict[str, str],
    ) -> ProcessResult:
        result = self.process_http_request(
            path=CLAUDE_HOOK_CONNECTOR_PATH,
            request_id=request_id,
            payload=payload,
            incoming_headers=incoming_headers,
        )
        if isinstance(result, StreamProcessResult):
            raise MiddlewareError(
                500,
                "MODEIO_INTERNAL_ERROR",
                "claude connector unexpectedly returned a stream result",
                retryable=False,
            )
        return result

    def _process_connector_hook(self, invocation: CanonicalInvocation) -> ProcessResult:
        session, on_plugin_error, shared_state, request_context = (
            self._start_invocation(invocation)
        )
        connector_capabilities = invocation.connector_capabilities.as_dict()
        journal = self.services.request_journal

        try:
            if invocation.phase == "pre_request":
                pre_result = self.plugin_manager.apply_pre_request(
                    session.active_plugins,
                    request_id=session.request_id,
                    endpoint_kind=invocation.endpoint_kind,
                    profile=session.profile,
                    request_body=invocation.request_body,
                    request_headers=invocation.incoming_headers,
                    context=request_context,
                    shared_state=shared_state,
                    on_plugin_error=on_plugin_error,
                    services=self._plugin_services,
                    connector_capabilities=connector_capabilities,
                )
                session.pre_actions = pre_result.actions
                session.degraded.extend(pre_result.degraded)
                if journal is not None:
                    journal.record_pre_result(
                        request_id=session.request_id,
                        effective_request_body=pre_result.body,
                        pre_actions=list(pre_result.actions),
                        degraded=list(pre_result.degraded),
                        findings=list(pre_result.findings),
                        blocked=pre_result.blocked,
                        block_message=pre_result.block_message,
                    )
                response_payload = build_claude_hook_response(
                    source_event=invocation.source_event,
                    blocked=pre_result.blocked,
                    block_message=pre_result.block_message,
                    findings=pre_result.findings,
                )
            elif invocation.phase == "post_response":
                post_result = self.plugin_manager.apply_post_response(
                    session.active_plugins,
                    request_id=session.request_id,
                    endpoint_kind=invocation.endpoint_kind,
                    profile=session.profile,
                    request_context=request_context,
                    response_body=invocation.response_body,
                    response_headers={},
                    shared_state=shared_state,
                    on_plugin_error=on_plugin_error,
                    services=self._plugin_services,
                    connector_capabilities=connector_capabilities,
                )
                session.post_actions = post_result.actions
                session.degraded.extend(post_result.degraded)
                if journal is not None:
                    journal.record_post_result(
                        request_id=session.request_id,
                        effective_response_body=post_result.body,
                        post_actions=list(post_result.actions),
                        degraded=list(post_result.degraded),
                        findings=list(post_result.findings),
                        blocked=post_result.blocked,
                        block_message=post_result.block_message,
                    )
                response_payload = build_claude_hook_response(
                    source_event=invocation.source_event,
                    blocked=post_result.blocked,
                    block_message=post_result.block_message,
                    findings=post_result.findings,
                )
            else:
                raise MiddlewareError(
                    500,
                    "MODEIO_INTERNAL_ERROR",
                    f"unsupported connector phase '{invocation.phase}'",
                    retryable=False,
                )

            headers = self._session_headers(session)
            if journal is not None:
                journal.finish_success(request_id=session.request_id)
            return ProcessResult(status=200, payload=response_payload, headers=headers)

        except MiddlewareError as error:
            if journal is not None:
                self._journal_finish_error(session.request_id, error)
            return self._error_process_result(session, error)
        except Exception:
            error = MiddlewareError(
                503,
                "MODEIO_INTERNAL_ERROR",
                "unexpected internal error",
                retryable=False,
            )
            if journal is not None:
                self._journal_finish_error(session.request_id, error)
            return self._error_process_result(session, error)
        finally:
            self._shutdown_session_plugins(session)

    def _process_stream_request(
        self,
        *,
        endpoint_kind: str,
        session: PipelineSession,
        on_plugin_error: str,
        shared_state: Dict[str, Any],
        request_context: Dict[str, Any],
        upstream_payload: Dict[str, Any],
        upstream_headers: Dict[str, str],
        connector_capabilities: Dict[str, bool],
    ) -> Union[ProcessResult, StreamProcessResult]:
        journal = self.services.request_journal
        if journal is not None:
            journal.mark_upstream_start(request_id=session.request_id)
        upstream_response = forward_upstream_stream(
            config=self.config,
            endpoint_kind=endpoint_kind,
            payload=upstream_payload,
            incoming_headers=upstream_headers,
        )
        if journal is not None:
            journal.record_upstream_result(
                request_id=session.request_id, response_body=None
            )

        post_start_result = self.plugin_manager.apply_post_stream_start(
            session.active_plugins,
            request_id=session.request_id,
            endpoint_kind=endpoint_kind,
            profile=session.profile,
            request_context=request_context,
            response_context={},
            shared_state=shared_state,
            on_plugin_error=on_plugin_error,
            services=self._plugin_services,
            connector_capabilities=connector_capabilities,
        )
        session.degraded.extend(post_start_result.degraded)
        session.post_actions = list(post_start_result.actions)
        if journal is not None:
            journal.record_post_result(
                request_id=session.request_id,
                effective_response_body=None,
                post_actions=list(post_start_result.actions) or ["stream"],
                degraded=list(post_start_result.degraded),
                findings=list(post_start_result.findings),
                blocked=post_start_result.blocked,
                block_message=post_start_result.block_message,
            )

        if post_start_result.blocked:
            upstream_response.close()
            session.upstream_called = True
            if journal is not None:
                journal.finish_error(
                    request_id=session.request_id,
                    error_code="MODEIO_PLUGIN_BLOCKED",
                    error_message=post_start_result.block_message,
                    blocked=True,
                    block_message=post_start_result.block_message,
                )
            return self._error_process_result(
                session,
                MiddlewareError(
                    403,
                    "MODEIO_PLUGIN_BLOCKED",
                    post_start_result.block_message,
                    retryable=False,
                    details={"phase": "post_stream_start"},
                ),
            )

        post_actions_seed = list(post_start_result.actions)
        session.post_actions = post_actions_seed or ["stream"]
        session.upstream_called = True
        headers = contract_headers(
            session.request_id,
            profile=session.profile,
            pre_actions=session.pre_actions,
            post_actions=session.post_actions,
            degraded=session.degraded,
            upstream_called=session.upstream_called,
        )
        headers["Content-Type"] = upstream_response.headers.get(
            "Content-Type", "text/event-stream"
        )
        headers["Cache-Control"] = "no-cache"
        headers["x-modeio-streaming"] = "true"

        return StreamProcessResult(
            status=200,
            headers=headers,
            stream=iter_transformed_sse_stream(
                upstream_response=upstream_response,
                plugin_manager=self.plugin_manager,
                active_plugins=session.active_plugins,
                request_id=session.request_id,
                endpoint_kind=endpoint_kind,
                profile=session.profile,
                request_context=request_context,
                shared_state=shared_state,
                on_plugin_error=on_plugin_error,
                degraded=session.degraded,
                services=self._plugin_services,
                connector_capabilities=connector_capabilities,
                on_finish=lambda: self._finish_stream_request(session),
            ),
            payload=None,
        )

    def _finish_stream_request(self, session: PipelineSession) -> None:
        journal = self.services.request_journal
        if journal is not None:
            journal.finish_success(request_id=session.request_id)
        self._release_stream_plugins(session)
