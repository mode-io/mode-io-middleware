#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from modeio_middleware.connectors.base import CanonicalInvocation, ConnectorAdapter
from modeio_middleware.connectors.claude_hooks import (
    CLAUDE_HOOK_CONNECTOR_PATH,
    ClaudeHookConnector,
    build_claude_hook_response,
)
from modeio_middleware.connectors.openai_http import OpenAIHttpConnector
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.invocation_router import InvocationRouter
from modeio_middleware.core.observability.service import build_request_journal_service
from modeio_middleware.core.pipeline_session import PipelineSession
from modeio_middleware.core.pipeline_orchestrator import PipelineOrchestrator
from modeio_middleware.core.plugin_manager import PluginManager
from modeio_middleware.core.profiles import DEFAULT_PROFILE
from modeio_middleware.core.response_assembler import ResponseAssembler
from modeio_middleware.core.response_models import ProcessResult, StreamProcessResult
from modeio_middleware.core.services.engine_services import EngineServices
from modeio_middleware.core.services.telemetry import PluginTelemetry
from modeio_middleware.core.stream_orchestrator import StreamOrchestrator
from modeio_middleware.core.upstream_transport import UpstreamTransport


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


def _build_runtime_services(
    service_config: Optional[Dict[str, Any]],
    *,
    request_journal=None,
) -> EngineServices:
    if request_journal is None:
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
    def __init__(
        self,
        runtime_config: GatewayRuntimeConfig,
        *,
        request_journal=None,
    ):
        self.config = runtime_config
        self.plugin_manager = PluginManager(
            runtime_config.plugins or {},
            preset_registry=runtime_config.preset_registry or {},
            config_base_dir=runtime_config.config_base_dir,
        )
        self.services = _build_runtime_services(
            runtime_config.service_config,
            request_journal=request_journal,
        )
        self._plugin_services = self.services.as_plugin_services()
        connectors: tuple[ConnectorAdapter, ...] = (
            ClaudeHookConnector(),
            OpenAIHttpConnector(),
        )
        self._response_assembler = ResponseAssembler()
        self._invocation_router = InvocationRouter(
            connectors=connectors,
            default_profile=runtime_config.default_profile,
            upstream_chat_completions_url=runtime_config.upstream_chat_completions_url,
            upstream_responses_url=runtime_config.upstream_responses_url,
        )
        self._pipeline = PipelineOrchestrator(
            config=runtime_config,
            plugin_manager=self.plugin_manager,
        )
        self._upstream_transport = UpstreamTransport(config=runtime_config)
        self._stream_orchestrator = StreamOrchestrator(
            plugin_manager=self.plugin_manager,
            upstream_transport=self._upstream_transport,
            response_assembler=self._response_assembler,
            plugin_services=self._plugin_services,
            request_journal=self.services.request_journal,
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

    def _new_session(self, *, request_id: str) -> PipelineSession:
        return self._pipeline.new_session(request_id=request_id)

    def _session_headers(self, session: PipelineSession) -> Dict[str, str]:
        return self._response_assembler.session_headers(session)

    def _response_headers(
        self,
        session: PipelineSession,
        base_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        return self._response_assembler.response_headers(session, base_headers)

    def _error_process_result(
        self, session: PipelineSession, error: MiddlewareError
    ) -> ProcessResult:
        return self._response_assembler.error_result(session, error)

    def _shutdown_session_plugins(self, session: PipelineSession) -> None:
        self._pipeline.shutdown_session_plugins(session)

    def _start_invocation(
        self,
        invocation: CanonicalInvocation,
    ) -> tuple[PipelineSession, str, Dict[str, Any], Dict[str, Any]]:
        session, on_plugin_error, shared_state = self._pipeline.start_invocation(
            invocation
        )
        request_context = self._invocation_router.build_request_context(invocation)
        return session, on_plugin_error, shared_state, request_context

    def _release_stream_plugins(self, session: PipelineSession) -> None:
        self._pipeline.release_stream_plugins(session)

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
            invocation = self._invocation_router.parse_http_request(
                path=path,
                request_id=request_id,
                payload=payload,
                incoming_headers=incoming_headers,
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
                stream_result = self._stream_orchestrator.process(
                    endpoint_kind=invocation.endpoint_kind,
                    session=session,
                    on_plugin_error=on_plugin_error,
                    shared_state=shared_state,
                    request_context=response_request_context,
                    upstream_payload=pre_result.body,
                    upstream_headers=pre_result.headers,
                    connector_capabilities=connector_capabilities,
                    on_finish=lambda: self._finish_stream_request(session),
                )
                streaming_response = isinstance(stream_result, StreamProcessResult)
                return stream_result

            if journal is not None:
                journal.mark_upstream_start(request_id=session.request_id)
            session.upstream_called = True
            upstream_response = self._upstream_transport.forward_json(
                endpoint_kind=invocation.endpoint_kind,
                payload=pre_result.body,
                incoming_headers=pre_result.headers,
            )
            if journal is not None:
                journal.record_upstream_result(
                    request_id=session.request_id,
                    response_body=upstream_response.payload,
                )

            post_result = self.plugin_manager.apply_post_response(
                session.active_plugins,
                request_id=session.request_id,
                endpoint_kind=invocation.endpoint_kind,
                profile=session.profile,
                request_context=response_request_context,
                response_body=upstream_response.payload,
                response_headers=upstream_response.headers,
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

            headers = self._response_headers(session, post_result.headers)
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

    def _finish_stream_request(self, session: PipelineSession) -> None:
        journal = self.services.request_journal
        if journal is not None:
            journal.finish_success(request_id=session.request_id)
        self._release_stream_plugins(session)
