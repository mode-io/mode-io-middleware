#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, Dict, Iterator, TYPE_CHECKING

import httpx

from modeio_middleware.core.contracts import ENDPOINT_CHAT_COMPLETIONS, ENDPOINT_RESPONSES
from modeio_middleware.core.errors import MiddlewareError

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
REQUEST_STRIP_HEADERS = HOP_BY_HOP_HEADERS | {"content-length", "host"}
RESPONSE_STRIP_HEADERS = HOP_BY_HOP_HEADERS | {
    "content-encoding",
    "content-length",
    "content-type",
}


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


def _build_upstream_headers(
    incoming_headers: Dict[str, str],
    *,
    upstream_api_key_env: str,
) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for key, value in incoming_headers.items():
        key_text = str(key)
        lower_key = key_text.lower()
        if lower_key in REQUEST_STRIP_HEADERS or lower_key.startswith("x-modeio-"):
            continue
        headers[key_text] = str(value)

    headers["Content-Type"] = "application/json"
    authorization = headers.get("authorization") or headers.get("Authorization")
    if not authorization:
        fallback_key = os.environ.get(upstream_api_key_env, "").strip()
        if fallback_key:
            authorization = f"Bearer {fallback_key}"
    if authorization:
        headers["Authorization"] = authorization
    return headers


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


def _resolve_upstream_url(config: "GatewayRuntimeConfig", endpoint_kind: str) -> str:
    if endpoint_kind == ENDPOINT_CHAT_COMPLETIONS:
        return config.upstream_chat_completions_url
    if endpoint_kind == ENDPOINT_RESPONSES:
        return config.upstream_responses_url
    raise MiddlewareError(
        500,
        "MODEIO_INTERNAL_ERROR",
        f"unsupported endpoint kind '{endpoint_kind}'",
        retryable=False,
    )


def forward_upstream_json(
    *,
    config: "GatewayRuntimeConfig",
    endpoint_kind: str,
    payload: Dict[str, Any],
    incoming_headers: Dict[str, str],
) -> UpstreamJsonResponse:
    headers = _build_upstream_headers(
        incoming_headers,
        upstream_api_key_env=config.upstream_api_key_env,
    )
    upstream_url = _resolve_upstream_url(config, endpoint_kind)
    last_exception: httpx.RequestError | None = None

    for attempt in range(1 + MAX_RETRIES):
        try:
            with httpx.Client(timeout=_timeout_config(config.upstream_timeout_seconds, stream=False)) as client:
                response = client.post(upstream_url, headers=headers, json=payload)
                if response.status_code in (502, 503, 504) and attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF * (2**attempt))
                    continue

                response_headers = _sanitize_upstream_response_headers(response.headers)
                if response.status_code >= 400:
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
) -> StreamingUpstreamResponse:
    headers = _build_upstream_headers(
        incoming_headers,
        upstream_api_key_env=config.upstream_api_key_env,
    )
    headers["Accept"] = "text/event-stream"
    upstream_url = _resolve_upstream_url(config, endpoint_kind)
    last_exception: httpx.RequestError | None = None

    for attempt in range(1 + MAX_RETRIES):
        client = httpx.Client(timeout=_timeout_config(config.upstream_timeout_seconds, stream=True))
        try:
            request = client.build_request("POST", upstream_url, headers=headers, json=payload)
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
