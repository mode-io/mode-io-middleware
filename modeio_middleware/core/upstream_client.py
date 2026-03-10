#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, Dict, Iterator, TYPE_CHECKING
from urllib.parse import urlencode

import httpx

from modeio_middleware.core.client_auth import (
    inspect_client_native_auth,
    record_client_native_failure,
)
from modeio_middleware.core.contracts import ENDPOINT_CHAT_COMPLETIONS, ENDPOINT_RESPONSES
from modeio_middleware.core.errors import MiddlewareError
from modeio_middleware.core.provider_auth import TRANSPORT_CODEX_NATIVE

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
    client_name: str,
    client_provider_name: str | None,
    upstream_api_key_env: str,
) -> tuple[Dict[str, str], Any, bool]:
    headers: Dict[str, str] = {}
    for key, value in incoming_headers.items():
        key_text = str(key)
        lower_key = key_text.lower()
        if lower_key in REQUEST_STRIP_HEADERS or lower_key.startswith("x-modeio-"):
            continue
        headers[key_text] = str(value)

    headers["Content-Type"] = "application/json"
    inspection = inspect_client_native_auth(
        client_name=client_name,
        client_provider_name=client_provider_name,
    )
    incoming_authorization = None
    for key, value in incoming_headers.items():
        if key.lower() == "authorization":
            incoming_authorization = str(value)
            break
    explicit_incoming_auth = bool(
        incoming_authorization
        and incoming_authorization.strip().lower()
        not in {"bearer modeio-middleware", "modeio-middleware"}
    )
    if explicit_incoming_auth:
        authorization = incoming_authorization
    else:
        authorization = inspection.authorization if inspection.ready else None

    fallback_key = os.environ.get(upstream_api_key_env, "").strip()
    used_managed_fallback = False
    if fallback_key and not explicit_incoming_auth and not inspection.ready:
        authorization = f"Bearer {fallback_key}"
        used_managed_fallback = True
    if authorization:
        headers["Authorization"] = authorization
    account_id = inspection.metadata.get("accountId") if isinstance(inspection.metadata, dict) else None
    if isinstance(account_id, str) and account_id.strip():
        headers.setdefault("ChatGPT-Account-Id", account_id.strip())
    return headers, inspection, used_managed_fallback


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


def _resolve_models_url(config: "GatewayRuntimeConfig") -> str:
    for candidate in (
        config.upstream_chat_completions_url,
        config.upstream_responses_url,
    ):
        text = str(candidate).rstrip("/")
        for suffix in ("/chat/completions", "/responses"):
            if text.endswith(suffix):
                return text[: -len(suffix)] + "/models"
    raise MiddlewareError(
        500,
        "MODEIO_INTERNAL_ERROR",
        "unable to derive upstream models URL",
        retryable=False,
    )


def _transport_endpoint_url(
    *,
    config: "GatewayRuntimeConfig",
    endpoint_kind: str,
    inspection: Any,
    used_managed_fallback: bool,
) -> str:
    metadata = getattr(inspection, "metadata", None)
    override_base = metadata.get("overrideBaseUrl") if isinstance(metadata, dict) else None
    if isinstance(override_base, str) and override_base.strip() and not used_managed_fallback:
        normalized_base = override_base.rstrip("/")
        if endpoint_kind == ENDPOINT_RESPONSES:
            return f"{normalized_base}/responses"
        if endpoint_kind == ENDPOINT_CHAT_COMPLETIONS:
            return f"{normalized_base}/chat/completions"
    if _use_codex_native_transport(inspection, used_managed_fallback):
        base_url = metadata.get("nativeBaseUrl") if isinstance(metadata, dict) else None
        if isinstance(base_url, str) and base_url.strip():
            normalized_base = base_url.rstrip("/")
            if endpoint_kind == ENDPOINT_RESPONSES:
                return f"{normalized_base}/responses"
            if endpoint_kind == ENDPOINT_CHAT_COMPLETIONS:
                return f"{normalized_base}/responses"
    return _resolve_upstream_url(config, endpoint_kind)


def _transport_models_url(
    *,
    config: "GatewayRuntimeConfig",
    inspection: Any,
    used_managed_fallback: bool,
) -> str:
    metadata = getattr(inspection, "metadata", None)
    override_base = metadata.get("overrideBaseUrl") if isinstance(metadata, dict) else None
    if isinstance(override_base, str) and override_base.strip() and not used_managed_fallback:
        return override_base.rstrip("/") + "/models"
    if _use_codex_native_transport(inspection, used_managed_fallback):
        base_url = metadata.get("nativeBaseUrl") if isinstance(metadata, dict) else None
        if isinstance(base_url, str) and base_url.strip():
            return base_url.rstrip("/") + "/models"
    return _resolve_models_url(config)


def _apply_model_override(payload: Dict[str, Any], inspection: Any) -> Dict[str, Any]:
    metadata = getattr(inspection, "metadata", None)
    fallback_model_id = metadata.get("fallbackModelId") if isinstance(metadata, dict) else None
    if not isinstance(fallback_model_id, str) or not fallback_model_id.strip():
        return payload
    updated = dict(payload)
    updated["model"] = fallback_model_id
    return updated


def _use_codex_native_transport(inspection: Any, used_managed_fallback: bool) -> bool:
    if getattr(inspection, "transport", None) != TRANSPORT_CODEX_NATIVE:
        return False
    if used_managed_fallback:
        return False
    metadata = getattr(inspection, "metadata", None)
    native_base = metadata.get("nativeBaseUrl") if isinstance(metadata, dict) else None
    return isinstance(native_base, str) and bool(native_base.strip())


def _to_codex_input_item(role: str, content: Any) -> Dict[str, Any]:
    normalized_role = role if role in {"user", "assistant", "developer"} else "user"
    if isinstance(content, list):
        normalized = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                normalized.append({"type": "input_text", "text": item["text"]})
            elif isinstance(item, dict) and item.get("type") == "input_text" and isinstance(item.get("text"), str):
                normalized.append({"type": "input_text", "text": item["text"]})
        if normalized:
            return {"type": "message", "role": normalized_role, "content": normalized}
    if isinstance(content, str):
        return {"type": "message", "role": normalized_role, "content": [{"type": "input_text", "text": content}]}
    return {"type": "message", "role": normalized_role, "content": []}


def _normalize_codex_native_model(model_name: Any) -> Any:
    if not isinstance(model_name, str):
        return model_name
    stripped = model_name.strip()
    if stripped == "gpt-5-nano":
        return "gpt-5.4"
    return stripped


def _normalize_codex_reasoning(reasoning: Any) -> Any:
    if not isinstance(reasoning, dict):
        return reasoning
    normalized = dict(reasoning)
    effort = normalized.get("effort")
    if effort == "minimal":
        normalized["effort"] = "none"
    return normalized


def _codex_native_payload(endpoint_kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if endpoint_kind == ENDPOINT_CHAT_COMPLETIONS:
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        system_messages = [
            item.get("content")
            for item in messages
            if isinstance(item, dict) and item.get("role") == "system" and isinstance(item.get("content"), str)
        ]
        input_items = [
            _to_codex_input_item(str(item.get("role") or "user"), item.get("content"))
            for item in messages
            if isinstance(item, dict) and item.get("role") != "system"
        ]
        return {
            "model": _normalize_codex_native_model(payload.get("model")),
            "instructions": "\n\n".join(system_messages) if system_messages else "You are Codex",
            "input": input_items,
            "stream": True,
            "store": False,
        }

    transformed = dict(payload)
    transformed["model"] = _normalize_codex_native_model(transformed.get("model"))
    transformed["store"] = False
    transformed["stream"] = True
    transformed.pop("max_output_tokens", None)
    transformed["reasoning"] = _normalize_codex_reasoning(transformed.get("reasoning"))

    instructions = transformed.get("instructions")
    input_value = transformed.get("input")
    if isinstance(input_value, list):
        instructions_parts = []
        normalized_items = []
        for item in input_value:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user")
            content = item.get("content")
            if role in {"system", "developer"}:
                if isinstance(content, str) and content.strip():
                    instructions_parts.append(content.strip())
                    continue
            normalized_items.append(_to_codex_input_item(role, content))
        transformed["input"] = normalized_items
        if not isinstance(instructions, str) or not instructions.strip():
            transformed["instructions"] = (
                "\n\n".join(instructions_parts) if instructions_parts else "You are Codex"
            )
    elif isinstance(input_value, str):
        transformed["input"] = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": input_value}],
            }
        ]
        if not isinstance(instructions, str) or not instructions.strip():
            transformed["instructions"] = "You are Codex"
    elif not isinstance(instructions, str) or not instructions.strip():
        transformed["instructions"] = "You are Codex"
    return transformed


def _postprocess_models_payload(response_payload: Dict[str, Any], inspection: Any) -> Dict[str, Any]:
    if getattr(inspection, "transport", None) != TRANSPORT_CODEX_NATIVE:
        return response_payload
    models = response_payload.get("models")
    if not isinstance(models, list):
        return response_payload
    updated = dict(response_payload)
    rewritten = []
    changed = False
    for item in models:
        if not isinstance(item, dict):
            rewritten.append(item)
            continue
        current = dict(item)
        if current.get("supports_websockets") is not False:
            current["supports_websockets"] = False
            changed = True
        if current.get("prefer_websockets") is not False:
            current["prefer_websockets"] = False
            changed = True
        rewritten.append(current)
    if not changed:
        return response_payload
    updated["models"] = rewritten
    return updated


def forward_upstream_json(
    *,
    config: "GatewayRuntimeConfig",
    endpoint_kind: str,
    payload: Dict[str, Any],
    incoming_headers: Dict[str, str],
    client_name: str = "unknown",
    client_provider_name: str | None = None,
) -> UpstreamJsonResponse:
    headers, inspection, used_managed_fallback = _build_upstream_headers(
        incoming_headers,
        client_name=client_name,
        client_provider_name=client_provider_name,
        upstream_api_key_env=config.upstream_api_key_env,
    )
    upstream_url = _transport_endpoint_url(
        config=config,
        endpoint_kind=endpoint_kind,
        inspection=inspection,
        used_managed_fallback=used_managed_fallback,
    )
    request_payload = (
        _codex_native_payload(endpoint_kind, payload)
        if _use_codex_native_transport(inspection, used_managed_fallback)
        and endpoint_kind in {ENDPOINT_RESPONSES, ENDPOINT_CHAT_COMPLETIONS}
        else payload
    )
    request_payload = _apply_model_override(request_payload, inspection)
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
                    if not used_managed_fallback:
                        record_client_native_failure(
                            client_name=client_name,
                            client_provider_name=client_provider_name,
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
    client_name: str = "unknown",
    client_provider_name: str | None = None,
) -> StreamingUpstreamResponse:
    headers, inspection, used_managed_fallback = _build_upstream_headers(
        incoming_headers,
        client_name=client_name,
        client_provider_name=client_provider_name,
        upstream_api_key_env=config.upstream_api_key_env,
    )
    headers["Accept"] = "text/event-stream"
    upstream_url = _transport_endpoint_url(
        config=config,
        endpoint_kind=endpoint_kind,
        inspection=inspection,
        used_managed_fallback=used_managed_fallback,
    )
    request_payload = (
        _codex_native_payload(endpoint_kind, payload)
        if _use_codex_native_transport(inspection, used_managed_fallback)
        and endpoint_kind in {ENDPOINT_RESPONSES, ENDPOINT_CHAT_COMPLETIONS}
        else payload
    )
    request_payload = _apply_model_override(request_payload, inspection)
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
            if not used_managed_fallback:
                record_client_native_failure(
                    client_name=client_name,
                    client_provider_name=client_provider_name,
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
    client_name: str = "unknown",
    client_provider_name: str | None = None,
    query_params: Dict[str, str] | None = None,
) -> UpstreamJsonResponse:
    headers, inspection, used_managed_fallback = _build_upstream_headers(
        incoming_headers,
        client_name=client_name,
        client_provider_name=client_provider_name,
        upstream_api_key_env=config.upstream_api_key_env,
    )
    upstream_url = _transport_models_url(
        config=config,
        inspection=inspection,
        used_managed_fallback=used_managed_fallback,
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
        if not used_managed_fallback:
            record_client_native_failure(
                client_name=client_name,
                client_provider_name=client_provider_name,
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
        payload=_postprocess_models_payload(response_payload, inspection),
        headers=response_headers,
    )
