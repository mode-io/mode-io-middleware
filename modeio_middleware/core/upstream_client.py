#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, Dict, Iterator, TYPE_CHECKING
from urllib.parse import urlencode

import httpx

from modeio_middleware.connectors.client_identity import CLIENT_OPENCLAW
from modeio_middleware.core.client_auth import (
    inspect_client_native_auth,
    record_client_native_failure,
    resolve_client_inspection_auth_material,
    resolve_client_inspection_credential,
    resolve_client_inspection_upstream_plan,
    resolve_client_route_upstream_plan,
)
from modeio_middleware.core.contracts import (
    ENDPOINT_ANTHROPIC_MESSAGES,
    ENDPOINT_RESPONSES,
)
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.request_context import ClientRouteContext
from modeio_middleware.core.upstream_plan import (
    ResolvedAuthMaterial,
    ResolvedClientUpstreamAuth,
    ResolvedCredential,
)
from modeio_middleware.core.upstream_strategy import strategy_for_plan

if TYPE_CHECKING:
    from modeio_middleware.core.engine import GatewayRuntimeConfig

MAX_RETRIES = 2
RETRY_BACKOFF = 1.0
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
REQUEST_STRIP_HEADERS = HOP_BY_HOP_HEADERS | {
    "content-encoding",
    "content-length",
    "host",
}
RESPONSE_STRIP_HEADERS = HOP_BY_HOP_HEADERS | {
    "content-encoding",
    "content-length",
    "content-type",
}
AUTH_HEADER_NAMES = {
    "authorization",
    "x-api-key",
    "api-key",
}
ANTHROPIC_VERSION_HEADER = "anthropic-version"
ANTHROPIC_DEFAULT_VERSION = "2023-06-01"
LOCAL_AUTH_PLACEHOLDER_VALUES = {"bearer modeio-middleware", "modeio-middleware"}


@dataclass(frozen=True)
class UpstreamJsonResponse:
    payload: Dict[str, Any]
    headers: Dict[str, str]


class StreamingUpstreamResponse:
    def __init__(self, *, client: httpx.Client, response: httpx.Response):
        self._client = client
        self._response = response
        self.content_type = str(response.headers.get("Content-Type", "")).strip()
        self.headers = _sanitize_upstream_response_headers(response.headers)

    def iter_lines(self) -> Iterator[str]:
        for line in self._response.iter_lines():
            yield line

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._client.close()


def _timeout_config(timeout_seconds: int, *, stream: bool) -> httpx.Timeout:
    if stream:
        return httpx.Timeout(timeout_seconds, read=None)
    return httpx.Timeout(timeout_seconds)


def _should_retry_exception(error: httpx.RequestError) -> bool:
    return isinstance(error, (httpx.ConnectError, httpx.TimeoutException))


def _sanitize_upstream_response_headers(
    headers: httpx.Headers | Dict[str, str],
) -> Dict[str, str]:
    sanitized: Dict[str, str] = {}
    for key, value in headers.items():
        key_text = str(key)
        lower_key = key_text.lower()
        if lower_key in RESPONSE_STRIP_HEADERS or lower_key.startswith("x-modeio-"):
            continue
        sanitized[key_text] = str(value)
    return sanitized


def _strip_auth_headers(headers: Dict[str, str]) -> None:
    for key in list(headers.keys()):
        if key.lower() in AUTH_HEADER_NAMES:
            headers.pop(key, None)


def _ensure_header(headers: Dict[str, str], name: str, value: str) -> None:
    target = name.lower()
    for key in headers:
        if key.lower() == target:
            return
    headers[name] = value


def _looks_like_placeholder(value: str) -> bool:
    return value.strip().lower() in LOCAL_AUTH_PLACEHOLDER_VALUES


def _has_explicit_incoming_auth(incoming_headers: Dict[str, str]) -> bool:
    for key, value in incoming_headers.items():
        if key.lower() not in AUTH_HEADER_NAMES:
            continue
        if _looks_like_placeholder(str(value)):
            continue
        return True
    return False


def _unsupported_family_error(
    *,
    route_context: ClientRouteContext,
    resolved: ResolvedClientUpstreamAuth,
) -> MiddlewareError:
    provider_id = (
        route_context.client_provider_name
        or resolved.credential.provider_id
        or "unknown"
    )
    api_family = str(resolved.upstream_plan.unsupported_family or "unknown").strip() or "unknown"
    details = {
        "client": route_context.client_name,
        "providerId": provider_id,
        "apiFamily": api_family,
    }
    if resolved.upstream_plan.supported_families:
        details["supportedFamilies"] = list(resolved.upstream_plan.supported_families)
    return MiddlewareError(
        400,
        "MODEIO_VALIDATION_ERROR",
        (
            f"OpenClaw provider '{provider_id}' uses unsupported API family "
            f"'{api_family}'. Supported families are openai-completions and "
            "anthropic-messages."
        ),
        retryable=False,
        details=details,
    )


def _resolve_client_upstream_auth(
    *,
    route_context: ClientRouteContext,
    explicit_incoming_auth: bool,
    upstream_api_key_env: str,
) -> ResolvedClientUpstreamAuth:
    if explicit_incoming_auth:
        upstream_plan = resolve_client_route_upstream_plan(route_context=route_context)
        return ResolvedClientUpstreamAuth(
            credential=ResolvedCredential(
                provider_id=route_context.client_provider_name or route_context.client_name,
                auth_kind="incoming_headers",
                source="incoming_headers",
                guaranteed=True,
            ),
            auth_material=ResolvedAuthMaterial(),
            upstream_plan=upstream_plan,
            inspection=None,
            explicit_incoming_auth=True,
            used_managed_fallback=False,
        )

    inspection = inspect_client_native_auth(
        client_name=route_context.client_name,
        client_provider_name=route_context.client_provider_name,
    )
    credential = resolve_client_inspection_credential(inspection)
    auth_material = resolve_client_inspection_auth_material(inspection)
    upstream_plan = resolve_client_inspection_upstream_plan(inspection)
    used_managed_fallback = False
    if not inspection.ready:
        fallback_key = os.environ.get(upstream_api_key_env, "").strip()
        if fallback_key:
            used_managed_fallback = True
            auth_material = ResolvedAuthMaterial(authorization=f"Bearer {fallback_key}")
    return ResolvedClientUpstreamAuth(
        credential=credential,
        auth_material=auth_material,
        upstream_plan=upstream_plan,
        inspection=inspection,
        explicit_incoming_auth=False,
        used_managed_fallback=used_managed_fallback,
    )


def _build_upstream_headers(
    incoming_headers: Dict[str, str],
    *,
    route_context: ClientRouteContext,
    endpoint_kind: str,
    upstream_api_key_env: str,
) -> tuple[Dict[str, str], ResolvedClientUpstreamAuth]:
    headers: Dict[str, str] = {}
    for key, value in incoming_headers.items():
        key_text = str(key)
        lower_key = key_text.lower()
        if lower_key in REQUEST_STRIP_HEADERS or lower_key.startswith("x-modeio-"):
            continue
        headers[key_text] = str(value)

    headers["Content-Type"] = "application/json"
    resolved = _resolve_client_upstream_auth(
        route_context=route_context,
        explicit_incoming_auth=_has_explicit_incoming_auth(incoming_headers),
        upstream_api_key_env=upstream_api_key_env,
    )

    if (
        route_context.client_name == CLIENT_OPENCLAW
        and resolved.upstream_plan.unsupported_family is not None
    ):
        raise _unsupported_family_error(
            route_context=route_context,
            resolved=resolved,
        )

    if not resolved.explicit_incoming_auth:
        _strip_auth_headers(headers)
        if resolved.auth_material.resolved_headers:
            headers.update(resolved.auth_material.resolved_headers)
        elif resolved.auth_material.authorization:
            headers["Authorization"] = resolved.auth_material.authorization

    if endpoint_kind == ENDPOINT_ANTHROPIC_MESSAGES:
        _ensure_header(headers, ANTHROPIC_VERSION_HEADER, ANTHROPIC_DEFAULT_VERSION)
    if resolved.auth_material.account_id:
        headers.setdefault("ChatGPT-Account-Id", resolved.auth_material.account_id)
    return headers, resolved


def _route_context(
    *,
    client_name: str,
    client_provider_name: str | None,
) -> ClientRouteContext:
    return ClientRouteContext(
        client_name=client_name,
        client_provider_name=client_provider_name,
    )


def _record_failure_if_needed(
    *,
    resolved: ResolvedClientUpstreamAuth,
    route_context: ClientRouteContext,
    status_code: int,
) -> None:
    if resolved.used_managed_fallback or resolved.explicit_incoming_auth:
        return
    record_client_native_failure(
        client_name=route_context.client_name,
        client_provider_name=route_context.client_provider_name,
        status_code=status_code,
    )


def forward_upstream_json(
    *,
    config: "GatewayRuntimeConfig",
    endpoint_kind: str,
    payload: Dict[str, Any],
    incoming_headers: Dict[str, str],
    route_context: ClientRouteContext | None = None,
    client_name: str = "unknown",
    client_provider_name: str | None = None,
) -> UpstreamJsonResponse:
    route_context = route_context or _route_context(
        client_name=client_name,
        client_provider_name=client_provider_name,
    )
    headers, resolved = _build_upstream_headers(
        incoming_headers,
        route_context=route_context,
        endpoint_kind=endpoint_kind,
        upstream_api_key_env=config.upstream_api_key_env,
    )
    strategy = strategy_for_plan(resolved.upstream_plan)
    upstream_url = strategy.endpoint_url(
        config=config,
        endpoint_kind=endpoint_kind,
        plan=resolved.upstream_plan,
    )
    request_payload = strategy.request_payload(
        endpoint_kind=endpoint_kind,
        payload=payload,
        plan=resolved.upstream_plan,
    )
    last_exception: httpx.RequestError | None = None

    for attempt in range(1 + MAX_RETRIES):
        try:
            with httpx.Client(timeout=_timeout_config(config.upstream_timeout_seconds, stream=False)) as client:
                response = client.post(upstream_url, headers=headers, json=request_payload)
                if response.status_code in (502, 503, 504) and attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF * (2**attempt))
                    continue

                response_headers = _sanitize_upstream_response_headers(response.headers)
                if response.status_code >= 400:
                    _record_failure_if_needed(
                        resolved=resolved,
                        route_context=route_context,
                        status_code=response.status_code,
                    )
                    retryable = response.status_code >= 500
                    mapped_status = response.status_code if response.status_code < 500 else 502
                    raise MiddlewareError(
                        mapped_status,
                        "MODEIO_UPSTREAM_ERROR",
                        f"upstream returned status {response.status_code}",
                        retryable=retryable,
                        details={"upstreamStatus": response.status_code},
                        headers=response_headers,
                    )

                try:
                    response_payload = response.json()
                except ValueError as error:
                    raise MiddlewareError(
                        502,
                        "MODEIO_UPSTREAM_INVALID_JSON",
                        "upstream response is not valid JSON",
                        retryable=False,
                        headers=response_headers,
                    ) from error

                if not isinstance(response_payload, dict):
                    raise MiddlewareError(
                        502,
                        "MODEIO_UPSTREAM_INVALID_JSON",
                        "upstream response root must be an object",
                        retryable=False,
                        headers=response_headers,
                    )
                return UpstreamJsonResponse(
                    payload=response_payload,
                    headers=response_headers,
                )
        except MiddlewareError:
            raise
        except httpx.RequestError as error:
            last_exception = error
            if _should_retry_exception(error) and attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * (2**attempt))
                continue
            raise MiddlewareError(
                502,
                "MODEIO_UPSTREAM_TIMEOUT",
                f"upstream request failed: {type(error).__name__}",
                retryable=True,
            ) from error

    raise MiddlewareError(
        502,
        "MODEIO_UPSTREAM_TIMEOUT",
        f"upstream request failed: {type(last_exception).__name__ if last_exception is not None else 'RequestError'}",
        retryable=True,
    )


def forward_upstream_stream(
    *,
    config: "GatewayRuntimeConfig",
    endpoint_kind: str,
    payload: Dict[str, Any],
    incoming_headers: Dict[str, str],
    route_context: ClientRouteContext | None = None,
    client_name: str = "unknown",
    client_provider_name: str | None = None,
) -> StreamingUpstreamResponse:
    route_context = route_context or _route_context(
        client_name=client_name,
        client_provider_name=client_provider_name,
    )
    headers, resolved = _build_upstream_headers(
        incoming_headers,
        route_context=route_context,
        endpoint_kind=endpoint_kind,
        upstream_api_key_env=config.upstream_api_key_env,
    )
    headers["Accept"] = "text/event-stream"
    strategy = strategy_for_plan(resolved.upstream_plan)
    upstream_url = strategy.endpoint_url(
        config=config,
        endpoint_kind=endpoint_kind,
        plan=resolved.upstream_plan,
    )
    request_payload = strategy.request_payload(
        endpoint_kind=endpoint_kind,
        payload=payload,
        plan=resolved.upstream_plan,
    )
    last_exception: httpx.RequestError | None = None

    for attempt in range(1 + MAX_RETRIES):
        client = httpx.Client(timeout=_timeout_config(config.upstream_timeout_seconds, stream=True))
        try:
            request = client.build_request(
                "POST", upstream_url, headers=headers, json=request_payload
            )
            response = client.send(request, stream=True)
        except httpx.RequestError as error:
            client.close()
            last_exception = error
            if _should_retry_exception(error) and attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * (2**attempt))
                continue
            raise MiddlewareError(
                502,
                "MODEIO_UPSTREAM_TIMEOUT",
                f"upstream request failed: {type(error).__name__}",
                retryable=True,
            ) from error

        if response.status_code in (502, 503, 504) and attempt < MAX_RETRIES:
            response.close()
            client.close()
            time.sleep(RETRY_BACKOFF * (2**attempt))
            continue

        if response.status_code >= 400:
            _record_failure_if_needed(
                resolved=resolved,
                route_context=route_context,
                status_code=response.status_code,
            )
            retryable = response.status_code >= 500
            mapped_status = response.status_code if response.status_code < 500 else 502
            response_headers = _sanitize_upstream_response_headers(response.headers)
            response.close()
            client.close()
            raise MiddlewareError(
                mapped_status,
                "MODEIO_UPSTREAM_ERROR",
                f"upstream returned status {response.status_code}",
                retryable=retryable,
                details={"upstreamStatus": response.status_code},
                headers=response_headers,
            )

        return StreamingUpstreamResponse(client=client, response=response)

    raise MiddlewareError(
        502,
        "MODEIO_UPSTREAM_TIMEOUT",
        f"upstream request failed: {type(last_exception).__name__ if last_exception is not None else 'RequestError'}",
        retryable=True,
    )


def forward_upstream_models_json(
    *,
    config: "GatewayRuntimeConfig",
    incoming_headers: Dict[str, str],
    route_context: ClientRouteContext | None = None,
    client_name: str = "unknown",
    client_provider_name: str | None = None,
    query_params: Dict[str, str] | None = None,
) -> UpstreamJsonResponse:
    route_context = route_context or _route_context(
        client_name=client_name,
        client_provider_name=client_provider_name,
    )
    headers, resolved = _build_upstream_headers(
        incoming_headers,
        route_context=route_context,
        endpoint_kind=ENDPOINT_RESPONSES,
        upstream_api_key_env=config.upstream_api_key_env,
    )
    strategy = strategy_for_plan(resolved.upstream_plan)
    upstream_url = strategy.models_url(
        config=config,
        plan=resolved.upstream_plan,
    )
    if query_params:
        upstream_url = f"{upstream_url}?{urlencode(query_params)}"

    try:
        with httpx.Client(timeout=_timeout_config(config.upstream_timeout_seconds, stream=False)) as client:
            response = client.get(upstream_url, headers=headers)
    except httpx.RequestError as error:
        raise MiddlewareError(
            502,
            "MODEIO_UPSTREAM_TIMEOUT",
            f"upstream request failed: {type(error).__name__}",
            retryable=True,
        ) from error

    response_headers = _sanitize_upstream_response_headers(response.headers)
    if response.status_code >= 400:
        _record_failure_if_needed(
            resolved=resolved,
            route_context=route_context,
            status_code=response.status_code,
        )
        retryable = response.status_code >= 500
        mapped_status = response.status_code if response.status_code < 500 else 502
        raise MiddlewareError(
            mapped_status,
            "MODEIO_UPSTREAM_ERROR",
            f"upstream returned status {response.status_code}",
            retryable=retryable,
            details={"upstreamStatus": response.status_code},
            headers=response_headers,
        )

    try:
        response_payload = response.json()
    except ValueError as error:
        raise MiddlewareError(
            502,
            "MODEIO_UPSTREAM_INVALID_JSON",
            "upstream response is not valid JSON",
            retryable=False,
            headers=response_headers,
        ) from error

    if not isinstance(response_payload, dict):
        raise MiddlewareError(
            502,
            "MODEIO_UPSTREAM_INVALID_JSON",
            "upstream response root must be an object",
            retryable=False,
            headers=response_headers,
        )

    return UpstreamJsonResponse(
        payload=strategy.postprocess_models_payload(
            response_payload,
            plan=resolved.upstream_plan,
        ),
        headers=response_headers,
    )
