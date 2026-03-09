#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

TraceStatus = Literal["completed", "blocked", "error", "stream_completed"]
TraceImpact = Literal["pass_through", "modified", "blocked", "warned", "mixed"]
TraceLifecycle = Literal[
    "none",
    "pre_request",
    "post_response",
    "pre_and_post",
    "stream",
    "pre_and_stream",
]


@dataclass(frozen=True)
class RequestJournalConfig:
    enabled: bool = True
    max_records: int = 500
    capture_bodies: bool = True
    max_body_chars: int = 20000
    sample_diff_paths: int = 20
    live_queue_size: int = 100


@dataclass(frozen=True)
class ChangeSummary:
    changed: bool
    add_count: int = 0
    remove_count: int = 0
    replace_count: int = 0
    sample_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class HookExecutionRecord:
    plugin_name: str
    hook_name: str
    effective_action: str
    duration_ms: float
    errored: bool
    reported_action: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class ImpactSummary:
    category: TraceImpact = "pass_through"
    actions: tuple[str, ...] = ()
    primary_plugin: str | None = None
    plugin_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class StreamSummary:
    event_count: int = 0
    blocked_during_stream: bool = False
    done_received: bool = False


@dataclass(frozen=True)
class RequestTraceRecord:
    sequence: int
    request_id: str
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    source: str
    client_name: str
    source_event: str
    endpoint_kind: str
    phase: str
    profile: str
    stream: bool
    status: TraceStatus
    blocked: bool
    block_message: str | None
    error_code: str | None
    error_message: str | None
    upstream_called: bool
    upstream_duration_ms: float | None
    original_request_body: dict[str, Any] | None
    effective_request_body: dict[str, Any] | None
    original_response_body: dict[str, Any] | None
    effective_response_body: dict[str, Any] | None
    request_change: ChangeSummary
    response_change: ChangeSummary
    pre_actions: tuple[str, ...] = ()
    post_actions: tuple[str, ...] = ()
    degraded: tuple[str, ...] = ()
    findings: tuple[dict[str, Any], ...] = ()
    hook_executions: tuple[HookExecutionRecord, ...] = ()
    impact: ImpactSummary = field(default_factory=ImpactSummary)
    stream_summary: StreamSummary = field(default_factory=StreamSummary)


@dataclass
class InFlightTrace:
    request_id: str
    started_at: datetime
    started_perf: float
    source: str
    client_name: str
    source_event: str
    endpoint_kind: str
    phase: str
    profile: str
    stream: bool
    original_request_body: dict[str, Any] | None = None
    effective_request_body: dict[str, Any] | None = None
    original_response_body: dict[str, Any] | None = None
    effective_response_body: dict[str, Any] | None = None
    upstream_called: bool = False
    upstream_started_perf: float | None = None
    upstream_duration_ms: float | None = None
    pre_actions: list[str] = field(default_factory=list)
    post_actions: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    hook_executions: list[HookExecutionRecord] = field(default_factory=list)
    blocked: bool = False
    block_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    stream_event_count: int = 0
    stream_blocked: bool = False
    stream_done_received: bool = False
