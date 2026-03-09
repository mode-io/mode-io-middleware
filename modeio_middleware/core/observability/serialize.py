#!/usr/bin/env python3

from __future__ import annotations

from typing import Any

from modeio_middleware.core.observability.derived import summarize_lifecycle
from modeio_middleware.core.observability.models import (
    ChangeSummary,
    HookExecutionRecord,
    RequestTraceRecord,
)


def isoformat_utc(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def serialize_change(change: ChangeSummary) -> dict[str, Any]:
    return {
        "changed": change.changed,
        "addCount": change.add_count,
        "removeCount": change.remove_count,
        "replaceCount": change.replace_count,
        "samplePaths": list(change.sample_paths),
    }


def serialize_hook(record: HookExecutionRecord) -> dict[str, Any]:
    return {
        "pluginName": record.plugin_name,
        "hookName": record.hook_name,
        "reportedAction": record.reported_action,
        "effectiveAction": record.effective_action,
        "durationMs": round(record.duration_ms, 3),
        "errored": record.errored,
        "errorType": record.error_type,
    }


def _impact_payload(record: RequestTraceRecord) -> dict[str, Any]:
    return {
        "impact": record.impact.category,
        "impactActions": list(record.impact.actions),
        "primaryPlugin": record.impact.primary_plugin,
        "pluginNames": list(record.impact.plugin_names),
    }


def _lifecycle_payload(record: RequestTraceRecord) -> dict[str, Any]:
    return {
        "lifecycle": summarize_lifecycle(
            request_change=record.request_change,
            response_change=record.response_change,
            hook_executions=record.hook_executions,
        )
    }


def serialize_summary(record: RequestTraceRecord) -> dict[str, Any]:
    return {
        "sequence": record.sequence,
        "requestId": record.request_id,
        "startedAt": isoformat_utc(record.started_at),
        "durationMs": round(record.duration_ms, 3),
        "source": record.source,
        "clientName": record.client_name,
        **_lifecycle_payload(record),
        "sourceEvent": record.source_event,
        "endpointKind": record.endpoint_kind,
        "phase": record.phase,
        "profile": record.profile,
        "stream": record.stream,
        "status": record.status,
        "blocked": record.blocked,
        "upstreamCalled": record.upstream_called,
        "requestChanged": record.request_change.changed,
        "responseChanged": record.response_change.changed,
        "preActions": list(record.pre_actions),
        "postActions": list(record.post_actions),
        "degradedCount": len(record.degraded),
        "findingCount": len(record.findings),
        "hookCount": len(record.hook_executions),
        **_impact_payload(record),
    }


def serialize_detail(record: RequestTraceRecord) -> dict[str, Any]:
    return {
        "sequence": record.sequence,
        "requestId": record.request_id,
        "startedAt": isoformat_utc(record.started_at),
        "finishedAt": isoformat_utc(record.finished_at),
        "durationMs": round(record.duration_ms, 3),
        "source": record.source,
        "clientName": record.client_name,
        **_lifecycle_payload(record),
        "sourceEvent": record.source_event,
        "endpointKind": record.endpoint_kind,
        "phase": record.phase,
        "profile": record.profile,
        "stream": record.stream,
        "status": record.status,
        "blocked": record.blocked,
        "blockMessage": record.block_message,
        "errorCode": record.error_code,
        "errorMessage": record.error_message,
        "upstreamCalled": record.upstream_called,
        "upstreamDurationMs": round(record.upstream_duration_ms, 3)
        if record.upstream_duration_ms is not None
        else None,
        "request": {
            "before": record.original_request_body,
            "after": record.effective_request_body,
            "change": serialize_change(record.request_change),
        },
        "response": {
            "before": record.original_response_body,
            "after": record.effective_response_body,
            "change": serialize_change(record.response_change),
        },
        "preActions": list(record.pre_actions),
        "postActions": list(record.post_actions),
        "degraded": list(record.degraded),
        "findings": list(record.findings),
        "hookExecutions": [serialize_hook(item) for item in record.hook_executions],
        "streamSummary": {
            "eventCount": record.stream_summary.event_count,
            "blockedDuringStream": record.stream_summary.blocked_during_stream,
            "doneReceived": record.stream_summary.done_received,
        },
        **_impact_payload(record),
    }
