#!/usr/bin/env python3

from __future__ import annotations

from typing import Dict, Optional

from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.http_contract import contract_headers, error_payload
from modeio_middleware.core.pipeline_session import PipelineSession
from modeio_middleware.core.response_models import ProcessResult


class ResponseAssembler:
    def session_headers(self, session: PipelineSession) -> Dict[str, str]:
        return contract_headers(
            session.request_id,
            profile=session.profile,
            pre_actions=session.pre_actions,
            post_actions=session.post_actions,
            degraded=session.degraded,
            upstream_called=session.upstream_called,
        )

    def response_headers(
        self,
        session: PipelineSession,
        base_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        headers = dict(base_headers or {})
        headers.update(self.session_headers(session))
        return headers

    def error_result(
        self, session: PipelineSession, error: MiddlewareError
    ) -> ProcessResult:
        payload = error_payload(
            session.request_id,
            error.code,
            error.message,
            retryable=error.retryable,
            details=error.details,
        )
        headers = self.response_headers(session, error.headers)
        return ProcessResult(status=error.status, payload=payload, headers=headers)
