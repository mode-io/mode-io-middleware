#!/usr/bin/env python3

from __future__ import annotations

import copy
from typing import Any

SENSITIVE_KEY_PARTS = (
    "authorization",
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
)
MASK_VALUE = "***"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _truncate_string(value: str, *, max_chars: int) -> str:
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    removed = len(value) - max_chars
    return value[:max_chars] + f"...<truncated {removed} chars>"


def _sanitize_value(value: Any, *, max_chars: int, key_hint: str | None = None) -> Any:
    if key_hint is not None and _is_sensitive_key(key_hint):
        return MASK_VALUE
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(item, max_chars=max_chars, key_hint=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item, max_chars=max_chars) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item, max_chars=max_chars) for item in value]
    if isinstance(value, str):
        return _truncate_string(value, max_chars=max_chars)
    return copy.deepcopy(value)


def sanitize_payload(
    payload: Any, *, capture_bodies: bool, max_chars: int
) -> dict[str, Any] | None:
    if not capture_bodies or payload is None:
        return None
    if not isinstance(payload, dict):
        return {"value": _sanitize_value(payload, max_chars=max_chars)}
    sanitized = _sanitize_value(payload, max_chars=max_chars)
    if not isinstance(sanitized, dict):
        return {"value": sanitized}
    return sanitized
