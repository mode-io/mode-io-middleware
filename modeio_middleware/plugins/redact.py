#!/usr/bin/env python3

from __future__ import annotations

import copy
from typing import Any, Dict

from modeio_middleware.plugins.base import MiddlewarePlugin
from modeio_middleware.core.payload_codec import (
    normalize_request_payload,
    normalize_response_payload,
    normalize_stream_event_payload,
)
from modeio_middleware.core.payload_types import NormalizedPayload
from modeio_middleware.plugins.redact_utils import restore_tokens_deep, shield_request_body


def _text_rewrite_operations(
    before_payload: Dict[str, Any],
    after_payload: NormalizedPayload,
) -> list[Dict[str, Any]]:
    before = NormalizedPayload.from_public_dict(before_payload)
    before_units = {unit.id: unit for unit in before.timeline}
    operations: list[Dict[str, Any]] = []
    for unit in after_payload.timeline:
        if not unit.writable or unit.text is None:
            continue
        previous = before_units.get(unit.id)
        if previous is None or previous.text == unit.text:
            continue
        operations.append(
            {
                "op": "replace_text",
                "target_unit_id": unit.id,
                "text": unit.text,
            }
        )
    return operations


class Plugin(MiddlewarePlugin):
    name = "redact"
    version = "0.1.0"

    def pre_request(self, hook_input: Dict[str, Any]) -> Dict[str, Any]:
        request_id = hook_input["request_id"]
        endpoint_kind = hook_input.get("endpoint_kind", "chat_completions")
        payload = hook_input["payload"]
        native = hook_input.get("native", {})
        request_body = native.get("request_body", {})

        updated_body, redaction_count, entries = shield_request_body(
            endpoint_kind,
            request_body,
            request_id=request_id,
        )

        plugin_state = hook_input.get("plugin_state")
        if isinstance(plugin_state, dict):
            plugin_state["entries"] = entries
            plugin_state["redactionCount"] = redaction_count

        if redaction_count <= 0:
            return {"action": "allow"}

        rewritten_payload = normalize_request_payload(
            endpoint_kind=endpoint_kind,
            source=str(hook_input.get("source") or "plugin_redact"),
            request_body=updated_body,
            connector_context=payload.get("metadata", {}).get("connectorContext", {}),
        )

        finding = {
            "class": "pii_exposure",
            "severity": "medium",
            "confidence": 0.8,
            "reason": "redact plugin shielded sensitive text before upstream call",
            "evidence": [f"redaction_count={redaction_count}"],
        }
        return {
            "action": "modify",
            "operations": _text_rewrite_operations(payload, rewritten_payload),
            "findings": [finding],
            "message": "sensitive text shielded before provider call",
        }

    def post_response(self, hook_input: Dict[str, Any]) -> Dict[str, Any]:
        plugin_state = hook_input.get("plugin_state")
        if not isinstance(plugin_state, dict):
            return {"action": "allow"}

        entries = plugin_state.get("entries", [])
        if not isinstance(entries, list) or not entries:
            return {"action": "allow"}

        native = hook_input.get("native", {})
        native_payload = copy.deepcopy(native.get("response_body", {}))
        restored_payload, replaced_total = restore_tokens_deep(native_payload, entries)

        if replaced_total <= 0:
            return {"action": "allow"}

        rewritten_payload = normalize_response_payload(
            endpoint_kind=hook_input.get("endpoint_kind", "chat_completions"),
            source=str(hook_input.get("source") or "plugin_redact"),
            response_body=restored_payload,
            connector_context=hook_input.get("payload", {}).get("metadata", {}).get(
                "connectorContext", {}
            ),
        )

        finding = {
            "class": "pii_restore",
            "severity": "low",
            "confidence": 0.8,
            "reason": "redact plugin restored shielded values in model response",
            "evidence": [f"restore_count={replaced_total}"],
        }
        return {
            "action": "modify",
            "operations": _text_rewrite_operations(
                hook_input["payload"], rewritten_payload
            ),
            "findings": [finding],
            "message": "shielded values restored in downstream response",
        }

    def post_stream_event(self, hook_input: Dict[str, Any]) -> Dict[str, Any]:
        plugin_state = hook_input.get("plugin_state")
        if not isinstance(plugin_state, dict):
            return {"action": "allow", "event": hook_input.get("event")}

        entries = plugin_state.get("entries", [])
        if not isinstance(entries, list) or not entries:
            return {"action": "allow"}

        native = hook_input.get("native", {})
        event = native.get("event")
        if not isinstance(event, dict):
            raise ValueError("stream event must be an object")

        if event.get("data_type") != "json":
            return {"action": "allow"}

        payload = event.get("payload")
        if not isinstance(payload, dict):
            return {"action": "allow"}

        restored_payload, replaced_total = restore_tokens_deep(payload, entries)
        if replaced_total <= 0:
            return {"action": "allow"}

        updated_event = dict(event)
        updated_event["payload"] = restored_payload
        rewritten_payload = normalize_stream_event_payload(
            endpoint_kind=hook_input.get("endpoint_kind", "chat_completions"),
            source=str(hook_input.get("source") or "plugin_redact"),
            event=updated_event,
            request_context=hook_input.get("request_context", {}),
        )

        finding = {
            "class": "pii_restore_stream",
            "severity": "low",
            "confidence": 0.8,
            "reason": "redact plugin restored shielded values in streamed response events",
            "evidence": [f"restore_count={replaced_total}"],
        }
        return {
            "action": "modify",
            "operations": _text_rewrite_operations(
                hook_input["payload"], rewritten_payload
            ),
            "findings": [finding],
            "message": "shielded values restored in stream events",
        }
