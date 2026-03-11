from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def build_inspection(**overrides: Any) -> SimpleNamespace:
    payload = {
        "provider_id": "openai",
        "auth_kind": "api_key",
        "ready": True,
        "guaranteed": True,
        "strategy": "test",
        "transport": "openai_compat",
        "reason": None,
        "auth_source": None,
        "path": None,
        "auth_env": None,
        "authorization": "Bearer test-token",
        "resolved_headers": {},
        "audience": None,
        "scopes": [],
        "metadata": {},
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)
