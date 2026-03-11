#!/usr/bin/env python3

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any

from modeio_middleware.core.observability.diffing import summarize_change
from modeio_middleware.core.observability.derived import (
    summarize_impact,
    summarize_lifecycle,
)
from modeio_middleware.core.observability.live import LiveEvent, LiveSubscriber
from modeio_middleware.core.observability.models import (
    HookExecutionRecord,
    InFlightTrace,
    RequestJournalConfig,
    RequestTraceRecord,
    StreamSummary,
)
from modeio_middleware.core.observability.sanitize import sanitize_payload
from modeio_middleware.core.observability.serialize import serialize_summary
from modeio_middleware.core.observability.store import (
    InMemoryRequestJournalStore,
    RequestJournalStore,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_bool(raw: Any, *, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    raise ValueError("must be boolean")


def _coerce_int(raw: Any, *, default: int, minimum: int) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError("must be an integer")
    return max(raw, minimum)


def parse_request_journal_config(
    service_config: dict[str, Any] | None,
) -> RequestJournalConfig:
    root = service_config or {}
    if not isinstance(root, dict):
        raise ValueError("config.services must be an object")
    raw = root.get("request_journal", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("config.services.request_journal must be an object")
    return RequestJournalConfig(
        enabled=_coerce_bool(raw.get("enabled"), default=True),
        max_records=_coerce_int(raw.get("max_records"), default=500, minimum=1),
        capture_bodies=_coerce_bool(raw.get("capture_bodies"), default=True),
        max_body_chars=_coerce_int(raw.get("max_body_chars"), default=20000, minimum=1),
        sample_diff_paths=_coerce_int(
            raw.get("sample_diff_paths"), default=20, minimum=1
        ),
        live_queue_size=_coerce_int(raw.get("live_queue_size"), default=100, minimum=1),
    )


class RequestJournalService:
    def __init__(
        self, *, config: RequestJournalConfig, store: RequestJournalStore | None = None
    ):
        self.config = config
        self.store = store or InMemoryRequestJournalStore(
            max_records=config.max_records
        )
        self._subscribers: set[LiveSubscriber] = set()

    def _sanitize_body(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        return sanitize_payload(
            payload,
            capture_bodies=self.config.capture_bodies,
            max_chars=self.config.max_body_chars,
        )

    def _sanitize_findings(
        self, findings: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        sanitized = self._sanitize_body({"findings": findings})
        if not isinstance(sanitized, dict):
            return []
        result = sanitized.get("findings", [])
        return result if isinstance(result, list) else []

    def _publish(self, event: str, data: dict[str, Any]) -> None:
        live_event = LiveEvent(event=event, data=data)
        stale: list[LiveSubscriber] = []
        for subscriber in list(self._subscribers):
            try:
                subscriber.publish(live_event)
            except Exception:
                stale.append(subscriber)
        for subscriber in stale:
            self._subscribers.discard(subscriber)

    def subscribe(self) -> LiveSubscriber:
        subscriber = LiveSubscriber(max_queue_size=self.config.live_queue_size)
        self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: LiveSubscriber) -> None:
        self._subscribers.discard(subscriber)
        subscriber.close()

    def start_request(
        self,
        *,
        request_id: str,
        source: str,
        client_name: str,
        source_event: str,
        endpoint_kind: str,
        phase: str,
        profile: str,
        stream: bool,
        request_payload: dict[str, Any] | None,
        response_payload: dict[str, Any] | None = None,
        native_request_body: dict[str, Any] | None = None,
        native_response_body: dict[str, Any] | None = None,
    ) -> None:
        try:
            sanitized_request = self._sanitize_body(request_payload)
            sanitized_response = self._sanitize_body(response_payload)
            sanitized_native_request = self._sanitize_body(native_request_body)
            sanitized_native_response = self._sanitize_body(native_response_body)
            trace = InFlightTrace(
                request_id=request_id,
                started_at=_utc_now(),
                started_perf=time.perf_counter(),
                source=source,
                client_name=client_name,
                source_event=source_event,
                endpoint_kind=endpoint_kind,
                phase=phase,
                profile=profile,
                stream=stream,
                original_request_body=sanitized_request,
                effective_request_body=sanitized_request,
                original_response_body=sanitized_response,
                effective_response_body=sanitized_response,
                native_request_body=sanitized_native_request,
                effective_native_request_body=sanitized_native_request,
                native_response_body=sanitized_native_response,
                effective_native_response_body=sanitized_native_response,
            )
            self.store.create_in_flight(trace)
        except Exception:
            return

    def record_pre_result(
        self,
        *,
        request_id: str,
        effective_request_payload: dict[str, Any] | None,
        effective_native_request_body: dict[str, Any] | None,
        pre_actions: list[str],
        degraded: list[str],
        findings: list[dict[str, Any]],
        blocked: bool,
        block_message: str | None,
    ) -> None:
        try:
            sanitized_body = self._sanitize_body(effective_request_payload)
            sanitized_native = self._sanitize_body(effective_native_request_body)
            sanitized_findings = self._sanitize_findings(findings)

            def updater(trace: InFlightTrace) -> None:
                trace.effective_request_body = sanitized_body
                trace.effective_native_request_body = sanitized_native
                trace.pre_actions = list(pre_actions)
                trace.degraded.extend(str(item) for item in degraded)
                trace.findings.extend(sanitized_findings)
                if blocked:
                    trace.blocked = True
                    trace.block_message = block_message

            self.store.update_in_flight(request_id, updater)
        except Exception:
            return

    def mark_upstream_start(self, *, request_id: str) -> None:
        try:

            def updater(trace: InFlightTrace) -> None:
                trace.upstream_called = True
                trace.upstream_started_perf = time.perf_counter()

            self.store.update_in_flight(request_id, updater)
        except Exception:
            return

    def record_upstream_result(
        self,
        *,
        request_id: str,
        response_payload: dict[str, Any] | None,
        native_response_body: dict[str, Any] | None,
    ) -> None:
        try:
            sanitized_response = self._sanitize_body(response_payload)
            sanitized_native_response = self._sanitize_body(native_response_body)

            def updater(trace: InFlightTrace) -> None:
                if trace.upstream_started_perf is not None:
                    trace.upstream_duration_ms = (
                        time.perf_counter() - trace.upstream_started_perf
                    ) * 1000
                if sanitized_response is not None:
                    trace.original_response_body = sanitized_response
                    trace.effective_response_body = sanitized_response
                if sanitized_native_response is not None:
                    trace.native_response_body = sanitized_native_response
                    trace.effective_native_response_body = sanitized_native_response

            self.store.update_in_flight(request_id, updater)
        except Exception:
            return

    def record_post_result(
        self,
        *,
        request_id: str,
        effective_response_payload: dict[str, Any] | None,
        effective_native_response_body: dict[str, Any] | None,
        post_actions: list[str],
        degraded: list[str],
        findings: list[dict[str, Any]],
        blocked: bool,
        block_message: str | None,
    ) -> None:
        try:
            sanitized_body = self._sanitize_body(effective_response_payload)
            sanitized_native = self._sanitize_body(effective_native_response_body)
            sanitized_findings = self._sanitize_findings(findings)

            def updater(trace: InFlightTrace) -> None:
                if sanitized_body is not None:
                    trace.effective_response_body = sanitized_body
                if sanitized_native is not None:
                    trace.effective_native_response_body = sanitized_native
                trace.post_actions = list(post_actions)
                trace.degraded.extend(str(item) for item in degraded)
                trace.findings.extend(sanitized_findings)
                if blocked:
                    trace.blocked = True
                    trace.block_message = block_message

            self.store.update_in_flight(request_id, updater)
        except Exception:
            return

    def record_hook_execution(
        self,
        *,
        request_id: str,
        plugin_name: str,
        hook_name: str,
        effective_action: str,
        duration_ms: float,
        errored: bool,
        reported_action: str | None = None,
        error_type: str | None = None,
    ) -> None:
        try:
            record = HookExecutionRecord(
                plugin_name=plugin_name,
                hook_name=hook_name,
                reported_action=reported_action,
                effective_action=effective_action,
                duration_ms=float(duration_ms),
                errored=bool(errored),
                error_type=error_type,
            )

            def updater(trace: InFlightTrace) -> None:
                trace.hook_executions.append(record)

            self.store.update_in_flight(request_id, updater)
        except Exception:
            return

    def record_stream_event(
        self, *, request_id: str, done_received: bool = False
    ) -> None:
        try:

            def updater(trace: InFlightTrace) -> None:
                trace.stream_event_count += 1
                trace.stream_done_received = trace.stream_done_received or done_received

            self.store.update_in_flight(request_id, updater)
        except Exception:
            return

    def record_stream_blocked(
        self, *, request_id: str, block_message: str | None
    ) -> None:
        try:

            def updater(trace: InFlightTrace) -> None:
                trace.stream_blocked = True
                trace.block_message = block_message or trace.block_message

            self.store.update_in_flight(request_id, updater)
        except Exception:
            return

    def _finalize_record(
        self, trace: InFlightTrace, *, error_code: str | None, error_message: str | None
    ) -> RequestTraceRecord:
        finished_at = _utc_now()
        duration_ms = (time.perf_counter() - trace.started_perf) * 1000
        blocked = trace.blocked or trace.stream_blocked
        status = "stream_completed" if trace.stream else "completed"
        if blocked:
            status = "blocked"
        if error_code is not None and not blocked:
            status = "error"
        request_change = summarize_change(
            trace.original_request_body,
            trace.effective_request_body,
            sample_limit=self.config.sample_diff_paths,
        )
        response_change = summarize_change(
            trace.original_response_body,
            trace.effective_response_body,
            sample_limit=self.config.sample_diff_paths,
        )
        impact = summarize_impact(
            blocked=blocked,
            request_change=request_change,
            response_change=response_change,
            hook_executions=tuple(trace.hook_executions),
        )
        return RequestTraceRecord(
            sequence=self.store.next_sequence(),
            request_id=trace.request_id,
            started_at=trace.started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            source=trace.source,
            client_name=trace.client_name,
            source_event=trace.source_event,
            endpoint_kind=trace.endpoint_kind,
            phase=trace.phase,
            profile=trace.profile,
            stream=trace.stream,
            status=status,
            blocked=blocked,
            block_message=trace.block_message,
            error_code=error_code,
            error_message=error_message,
            upstream_called=trace.upstream_called,
            upstream_duration_ms=trace.upstream_duration_ms,
            original_request_body=trace.original_request_body,
            effective_request_body=trace.effective_request_body,
            original_response_body=trace.original_response_body,
            effective_response_body=trace.effective_response_body,
            native_request_body=trace.native_request_body,
            effective_native_request_body=trace.effective_native_request_body,
            native_response_body=trace.native_response_body,
            effective_native_response_body=trace.effective_native_response_body,
            request_change=request_change,
            response_change=response_change,
            pre_actions=tuple(trace.pre_actions),
            post_actions=tuple(trace.post_actions),
            degraded=tuple(trace.degraded),
            findings=tuple(trace.findings),
            hook_executions=tuple(trace.hook_executions),
            impact=impact,
            stream_summary=StreamSummary(
                event_count=trace.stream_event_count,
                blocked_during_stream=trace.stream_blocked,
                done_received=trace.stream_done_received,
            ),
        )

    def finish_success(self, *, request_id: str) -> None:
        try:
            trace = self.store.pop_in_flight(request_id)
            if trace is None:
                return
            record = self._finalize_record(trace, error_code=None, error_message=None)
            self.store.append_record(record)
            self._publish("trace.completed", serialize_summary(record))
            self._publish("stats.updated", self.stats_snapshot())
        except Exception:
            return

    def finish_error(
        self,
        *,
        request_id: str,
        error_code: str,
        error_message: str,
        blocked: bool = False,
        block_message: str | None = None,
    ) -> None:
        try:
            trace = self.store.pop_in_flight(request_id)
            if trace is None:
                return
            if blocked:
                trace.blocked = True
                trace.block_message = (
                    block_message or trace.block_message or error_message
                )
            record = self._finalize_record(
                trace, error_code=error_code, error_message=error_message
            )
            self.store.append_record(record)
            self._publish("trace.completed", serialize_summary(record))
            self._publish("stats.updated", self.stats_snapshot())
        except Exception:
            return

    def list_records(
        self,
        *,
        limit: int,
        cursor: int | None = None,
        status: str | None = None,
        source: str | None = None,
        client_name: str | None = None,
        impact: str | None = None,
        lifecycle: str | None = None,
        endpoint_kind: str | None = None,
        profile: str | None = None,
    ) -> list[RequestTraceRecord]:
        return self.store.list_records(
            limit=max(1, limit),
            cursor=cursor,
            status=status,
            source=source,
            client_name=client_name,
            impact=impact,
            lifecycle=lifecycle,
            endpoint_kind=endpoint_kind,
            profile=profile,
        )

    def get_record(self, request_id: str) -> RequestTraceRecord | None:
        return self.store.get_record(request_id)

    def stats_snapshot(self) -> dict[str, Any]:
        records = self.store.snapshot_records()
        status_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        client_counts: dict[str, int] = {}
        impact_counts: dict[str, int] = {}
        lifecycle_counts: dict[str, int] = {}
        endpoint_counts: dict[str, int] = {}
        action_counts: dict[str, int] = {}
        plugin_counts: dict[str, dict[str, Any]] = {}
        changed_request_count = 0
        changed_response_count = 0
        latencies = [record.duration_ms for record in records]

        for record in records:
            status_counts[record.status] = status_counts.get(record.status, 0) + 1
            source_counts[record.source] = source_counts.get(record.source, 0) + 1
            client_counts[record.client_name] = (
                client_counts.get(record.client_name, 0) + 1
            )
            impact_counts[record.impact.category] = (
                impact_counts.get(record.impact.category, 0) + 1
            )
            lifecycle = summarize_lifecycle(
                request_change=record.request_change,
                response_change=record.response_change,
                hook_executions=record.hook_executions,
            )
            lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
            endpoint_counts[record.endpoint_kind] = (
                endpoint_counts.get(record.endpoint_kind, 0) + 1
            )
            if record.request_change.changed:
                changed_request_count += 1
            if record.response_change.changed:
                changed_response_count += 1
            for hook_record in record.hook_executions:
                action_counts[hook_record.effective_action] = (
                    action_counts.get(hook_record.effective_action, 0) + 1
                )
                plugin_stats = plugin_counts.setdefault(
                    hook_record.plugin_name,
                    {"calls": 0, "errors": 0, "actions": {}},
                )
                plugin_stats["calls"] += 1
                if hook_record.errored:
                    plugin_stats["errors"] += 1
                actions = plugin_stats["actions"]
                actions[hook_record.effective_action] = (
                    actions.get(hook_record.effective_action, 0) + 1
                )

        sorted_latencies = sorted(latencies)

        def percentile(value: float) -> float:
            if not sorted_latencies:
                return 0.0
            index = min(
                len(sorted_latencies) - 1,
                max(0, math.ceil((value / 100.0) * len(sorted_latencies)) - 1),
            )
            return round(sorted_latencies[index], 3)

        return {
            "retainedRecords": self.config.max_records,
            "completedRecords": len(records),
            "inFlightRecords": self.store.in_flight_count(),
            "changedRequestCount": changed_request_count,
            "changedResponseCount": changed_response_count,
            "byStatus": status_counts,
            "bySource": source_counts,
            "byClient": client_counts,
            "byImpact": impact_counts,
            "byLifecycle": lifecycle_counts,
            "byEndpointKind": endpoint_counts,
            "byAction": action_counts,
            "byPlugin": plugin_counts,
            "latencyMs": {
                "p50": percentile(50),
                "p95": percentile(95),
                "max": round(max(sorted_latencies), 3) if sorted_latencies else 0.0,
            },
        }


def build_request_journal_service(
    service_config: dict[str, Any] | None,
) -> RequestJournalService | None:
    config = parse_request_journal_config(service_config)
    if not config.enabled:
        return None
    return RequestJournalService(config=config)
