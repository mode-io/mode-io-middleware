#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.http_contract import safe_json_dumps
from modeio_middleware.core.observability.serialize import (
    serialize_detail,
    serialize_summary,
)
from modeio_middleware.runtime_control import GatewayController

LIVE_POLL_TIMEOUT_SECONDS = 5.0


def _json_response(payload: dict[str, Any], *, status_code: int = 200) -> Response:
    return Response(
        content=safe_json_dumps(payload),
        status_code=status_code,
        media_type="application/json; charset=utf-8",
    )


def _error_response(
    code: str,
    message: str,
    *,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> Response:
    payload = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return _json_response(payload, status_code=status_code)


def _parse_int(value: str | None, *, default: int | None = None) -> int | None:
    if value is None or not value.strip():
        return default
    return int(value.strip())


async def _parse_json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except ValueError as error:
        raise MiddlewareError(
            400,
            "MODEIO_VALIDATION_ERROR",
            "request body must be valid JSON",
            retryable=False,
        ) from error
    if not isinstance(payload, dict):
        raise MiddlewareError(
            400,
            "MODEIO_VALIDATION_ERROR",
            "request body must be a JSON object",
            retryable=False,
        )
    return payload


def _request_journal(controller: GatewayController):
    journal = controller.current_engine().services.request_journal
    if journal is None:
        return None
    return journal


def _format_sse(event: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def build_monitoring_routes(controller: GatewayController) -> list[Route]:
    async def events(request: Request) -> Response:
        journal = _request_journal(controller)
        if journal is None:
            return _error_response(
                "MODEIO_MONITORING_DISABLED", "monitoring is disabled", status_code=404
            )
        try:
            limit = min(
                max(_parse_int(request.query_params.get("limit"), default=50) or 50, 1),
                200,
            )
            cursor = _parse_int(request.query_params.get("cursor"))
        except ValueError:
            return _error_response(
                "MODEIO_VALIDATION_ERROR",
                "query parameter must be an integer",
                status_code=400,
            )

        records = journal.list_records(
            limit=limit,
            cursor=cursor,
            status=request.query_params.get("status"),
            source=request.query_params.get("source"),
            client_name=request.query_params.get("client"),
            impact=request.query_params.get("impact"),
            lifecycle=request.query_params.get("lifecycle")
            or request.query_params.get("stage"),
            endpoint_kind=request.query_params.get("endpoint_kind"),
            profile=request.query_params.get("profile"),
        )
        next_cursor = records[-1].sequence if len(records) == limit else None
        return _json_response(
            {
                "items": [serialize_summary(record) for record in records],
                "nextCursor": next_cursor,
            }
        )

    async def event_detail(request: Request) -> Response:
        journal = _request_journal(controller)
        if journal is None:
            return _error_response(
                "MODEIO_MONITORING_DISABLED", "monitoring is disabled", status_code=404
            )
        request_id = str(request.path_params["request_id"])
        record = journal.get_record(request_id)
        if record is None:
            return _error_response(
                "MODEIO_TRACE_NOT_FOUND", "trace not found", status_code=404
            )
        return _json_response(serialize_detail(record))

    async def stats(_request: Request) -> Response:
        journal = _request_journal(controller)
        if journal is None:
            return _error_response(
                "MODEIO_MONITORING_DISABLED", "monitoring is disabled", status_code=404
            )
        return _json_response(journal.stats_snapshot())

    async def live(request: Request) -> Response:
        journal = _request_journal(controller)
        if journal is None:
            return _error_response(
                "MODEIO_MONITORING_DISABLED", "monitoring is disabled", status_code=404
            )
        subscriber = journal.subscribe()

        async def stream():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    event = await asyncio.to_thread(
                        subscriber.get, LIVE_POLL_TIMEOUT_SECONDS
                    )
                    if event is None:
                        yield _format_sse("heartbeat", {})
                        continue
                    yield _format_sse(event.event, event.data)
            finally:
                journal.unsubscribe(subscriber)

        return StreamingResponse(stream(), media_type="text/event-stream")

    async def plugins(_request: Request) -> Response:
        try:
            payload = controller.monitoring_inventory()
        except MiddlewareError as error:
            return _error_response(
                error.code,
                error.message,
                status_code=error.status,
                details=error.details,
            )
        return _json_response(payload)

    async def update_profile_plugins(request: Request) -> Response:
        try:
            payload = await _parse_json_body(request)
            expected_generation = payload.get("expectedGeneration")
            if expected_generation is not None and not isinstance(
                expected_generation, int
            ):
                raise MiddlewareError(
                    400,
                    "MODEIO_VALIDATION_ERROR",
                    "field 'expectedGeneration' must be an integer",
                    retryable=False,
                )
            result = controller.update_profile_plugins(
                str(request.path_params["profile"]),
                plugin_order=payload.get("pluginOrder"),
                plugin_overrides=payload.get("pluginOverrides", {}),
                expected_generation=expected_generation,
            )
        except MiddlewareError as error:
            return _error_response(
                error.code,
                error.message,
                status_code=error.status,
                details=error.details,
            )
        return _json_response(result)

    return [
        Route("/modeio/api/plugins", plugins, methods=["GET"]),
        Route(
            "/modeio/api/profiles/{profile}/plugins",
            update_profile_plugins,
            methods=["PUT"],
        ),
        Route("/modeio/api/events/live", live, methods=["GET"]),
        Route("/modeio/api/events/{request_id}", event_detail, methods=["GET"]),
        Route("/modeio/api/events", events, methods=["GET"]),
        Route("/modeio/api/stats", stats, methods=["GET"]),
    ]
