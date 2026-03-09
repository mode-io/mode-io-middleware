#!/usr/bin/env python3

from __future__ import annotations

from collections import deque
from threading import RLock
from typing import Callable, Protocol

from modeio_middleware.core.observability.models import (
    InFlightTrace,
    RequestTraceRecord,
)
from modeio_middleware.core.observability.derived import summarize_lifecycle


class RequestJournalStore(Protocol):
    def create_in_flight(self, trace: InFlightTrace) -> None: ...

    def update_in_flight(
        self, request_id: str, updater: Callable[[InFlightTrace], None]
    ) -> bool: ...

    def pop_in_flight(self, request_id: str) -> InFlightTrace | None: ...

    def append_record(self, record: RequestTraceRecord) -> None: ...

    def get_record(self, request_id: str) -> RequestTraceRecord | None: ...

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
    ) -> list[RequestTraceRecord]: ...

    def snapshot_records(self) -> list[RequestTraceRecord]: ...

    def in_flight_count(self) -> int: ...

    def next_sequence(self) -> int: ...


class InMemoryRequestJournalStore:
    def __init__(self, *, max_records: int):
        self._lock = RLock()
        self._in_flight: dict[str, InFlightTrace] = {}
        self._records: deque[RequestTraceRecord] = deque(maxlen=max(1, max_records))
        self._by_request_id: dict[str, RequestTraceRecord] = {}
        self._sequence = 0

    def create_in_flight(self, trace: InFlightTrace) -> None:
        with self._lock:
            self._in_flight[trace.request_id] = trace

    def update_in_flight(
        self, request_id: str, updater: Callable[[InFlightTrace], None]
    ) -> bool:
        with self._lock:
            trace = self._in_flight.get(request_id)
            if trace is None:
                return False
            updater(trace)
            return True

    def pop_in_flight(self, request_id: str) -> InFlightTrace | None:
        with self._lock:
            return self._in_flight.pop(request_id, None)

    def append_record(self, record: RequestTraceRecord) -> None:
        with self._lock:
            evicted = (
                self._records[-1]
                if len(self._records) == self._records.maxlen
                else None
            )
            if evicted is not None:
                self._by_request_id.pop(evicted.request_id, None)
            self._records.appendleft(record)
            self._by_request_id[record.request_id] = record

    def get_record(self, request_id: str) -> RequestTraceRecord | None:
        with self._lock:
            return self._by_request_id.get(request_id)

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
        with self._lock:
            items: list[RequestTraceRecord] = []
            normalized_status = (
                status.strip().lower()
                if isinstance(status, str) and status.strip()
                else None
            )
            normalized_source = (
                source.strip().lower()
                if isinstance(source, str) and source.strip()
                else None
            )
            normalized_client = (
                client_name.strip().lower()
                if isinstance(client_name, str) and client_name.strip()
                else None
            )
            normalized_impact = (
                impact.strip().lower()
                if isinstance(impact, str) and impact.strip()
                else None
            )
            normalized_lifecycle = (
                lifecycle.strip().lower()
                if isinstance(lifecycle, str) and lifecycle.strip()
                else None
            )
            normalized_endpoint = (
                endpoint_kind.strip().lower()
                if isinstance(endpoint_kind, str) and endpoint_kind.strip()
                else None
            )
            normalized_profile = (
                profile.strip().lower()
                if isinstance(profile, str) and profile.strip()
                else None
            )
            for record in self._records:
                if cursor is not None and record.sequence >= cursor:
                    continue
                if normalized_status is not None and record.status != normalized_status:
                    continue
                if normalized_source is not None and record.source != normalized_source:
                    continue
                if (
                    normalized_client is not None
                    and record.client_name != normalized_client
                ):
                    continue
                if (
                    normalized_impact is not None
                    and record.impact.category != normalized_impact
                ):
                    continue
                if (
                    normalized_lifecycle is not None
                    and summarize_lifecycle(
                        request_change=record.request_change,
                        response_change=record.response_change,
                        hook_executions=record.hook_executions,
                    )
                    != normalized_lifecycle
                ):
                    continue
                if (
                    normalized_endpoint is not None
                    and record.endpoint_kind != normalized_endpoint
                ):
                    continue
                if (
                    normalized_profile is not None
                    and record.profile != normalized_profile
                ):
                    continue
                items.append(record)
                if len(items) >= max(limit, 1):
                    break
            return items

    def snapshot_records(self) -> list[RequestTraceRecord]:
        with self._lock:
            return list(self._records)

    def in_flight_count(self) -> int:
        with self._lock:
            return len(self._in_flight)

    def next_sequence(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence
