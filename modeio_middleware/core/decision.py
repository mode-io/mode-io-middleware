#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from modeio_middleware.core.contracts import HOOK_ACTION_ALLOW, VALID_HOOK_ACTIONS
from modeio_middleware.core.payload_mutations import normalize_semantic_operations


@dataclass
class HookDecision:
    action: str = HOOK_ACTION_ALLOW
    findings: List[Dict[str, Any]] = field(default_factory=list)
    message: Optional[str] = None
    operations: List[Dict[str, Any]] = field(default_factory=list)


def _coerce_findings(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("field 'findings' must be an array")

    findings: List[Dict[str, Any]] = []
    for finding in raw:
        if isinstance(finding, dict):
            findings.append(finding)
    return findings


def _to_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, HookDecision):
        result: Dict[str, Any] = {
            "action": payload.action,
            "findings": payload.findings,
            "message": payload.message,
        }
        if payload.operations:
            result["operations"] = payload.operations
        return result

    if payload is None:
        return {}

    if isinstance(payload, dict):
        return payload

    raise ValueError("plugin hook result must be an object")


def normalize_decision_payload(payload: Any, *, stream: bool) -> Dict[str, Any]:
    data = _to_payload(payload)

    action = str(data.get("action", HOOK_ACTION_ALLOW)).strip().lower()
    if action not in VALID_HOOK_ACTIONS:
        raise ValueError(f"unsupported plugin action '{action}'")

    message = data.get("message")
    if message is not None and not isinstance(message, str):
        raise ValueError("field 'message' must be a string")

    normalized: Dict[str, Any] = {
        "action": action,
        "findings": _coerce_findings(data.get("findings")),
        "message": message,
        "operations": normalize_semantic_operations(data.get("operations")),
    }

    return normalized
