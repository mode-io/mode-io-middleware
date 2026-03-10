#!/usr/bin/env python3

from __future__ import annotations

from typing import Any, Callable, Dict

from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.pipeline_session import PipelineSession
from modeio_middleware.core.plugin_manager import PluginManager
from modeio_middleware.core.response_assembler import ResponseAssembler
from modeio_middleware.core.response_models import ProcessResult, StreamProcessResult
from modeio_middleware.core.stream_relay import iter_transformed_sse_stream
from modeio_middleware.core.upstream_transport import UpstreamTransport


class StreamOrchestrator:
    def __init__(
        self,
        *,
        plugin_manager: PluginManager,
        upstream_transport: UpstreamTransport,
        response_assembler: ResponseAssembler,
        plugin_services: Dict[str, Any],
        request_journal: Any,
    ):
        self._plugin_manager = plugin_manager
        self._upstream_transport = upstream_transport
        self._response_assembler = response_assembler
        self._plugin_services = plugin_services
        self._request_journal = request_journal

    def process(
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
        on_finish: Callable[[], None],
    ) -> ProcessResult | StreamProcessResult:
        journal = self._request_journal
        if journal is not None:
            journal.mark_upstream_start(request_id=session.request_id)
        upstream_response = self._upstream_transport.forward_stream(
            endpoint_kind=endpoint_kind,
            payload=upstream_payload,
            incoming_headers=upstream_headers,
            client_name=request_context.get("client_name", "unknown"),
            client_provider_name=request_context.get("client_provider_name"),
        )
        if journal is not None:
            journal.record_upstream_result(
                request_id=session.request_id, response_body=None
            )

        post_start_result = self._plugin_manager.apply_post_stream_start(
            session.active_plugins,
            request_id=session.request_id,
            endpoint_kind=endpoint_kind,
            profile=session.profile,
            request_context=request_context,
            response_context={"response_headers": dict(upstream_response.headers)},
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
            return self._response_assembler.error_result(
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
        headers = self._response_assembler.response_headers(
            session, upstream_response.headers
        )
        headers["Content-Type"] = (
            upstream_response.content_type or "text/event-stream"
        )
        headers["Cache-Control"] = "no-cache"
        headers["x-modeio-streaming"] = "true"

        return StreamProcessResult(
            status=200,
            headers=headers,
            stream=iter_transformed_sse_stream(
                upstream_response=upstream_response,
                plugin_manager=self._plugin_manager,
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
                on_finish=on_finish,
            ),
            payload=None,
        )
