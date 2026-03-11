#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from typing import Any, Dict, Iterable, List

from modeio_middleware.core.payload_types import (
    NormalizedPayload,
    SemanticUnit,
    UNIT_KIND_ACTION,
    UNIT_KIND_INSTRUCTION,
    UNIT_KIND_MEDIA_REF,
    UNIT_KIND_OBSERVATION,
    UNIT_KIND_PROMPT,
    UNIT_KIND_RESPONSE,
)


class PayloadDenormalizationError(ValueError):
    pass


def _clone_native(native: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(native) if native else {}


def _json_arguments(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"raw": raw}
    return {}


def _dump_arguments(raw: Any) -> str:
    if isinstance(raw, dict):
        return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    if isinstance(raw, str):
        return raw
    return "{}"


def _ensure_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _content_blocks(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [block for block in value if isinstance(block, dict)]
    return []


def _append_text_unit(
    timeline: List[SemanticUnit],
    *,
    kind: str,
    origin: str,
    text: str,
    writable: bool,
    unit_id: str,
    attributes: Dict[str, Any],
    metadata: Dict[str, Any],
) -> None:
    timeline.append(
        SemanticUnit(
            id=unit_id,
            kind=kind,
            origin=origin,
            writable=writable,
            text=text,
            attributes=copy.deepcopy(attributes),
            metadata=copy.deepcopy(metadata),
        )
    )


def _append_media_unit(
    timeline: List[SemanticUnit],
    *,
    origin: str,
    unit_id: str,
    attributes: Dict[str, Any],
    metadata: Dict[str, Any],
) -> None:
    timeline.append(
        SemanticUnit(
            id=unit_id,
            kind=UNIT_KIND_MEDIA_REF,
            origin=origin,
            writable=False,
            attributes=copy.deepcopy(attributes),
            metadata=copy.deepcopy(metadata),
        )
    )


def _normalize_openai_chat_messages(messages: Iterable[Dict[str, Any]]) -> List[SemanticUnit]:
    timeline: List[SemanticUnit] = []
    for message_index, message in enumerate(messages):
        role = str(message.get("role") or "").strip() or "unknown"
        content = message.get("content")
        if isinstance(content, str):
            kind = {
                "system": UNIT_KIND_INSTRUCTION,
                "developer": UNIT_KIND_INSTRUCTION,
                "user": UNIT_KIND_PROMPT,
                "tool": UNIT_KIND_OBSERVATION,
            }.get(role, UNIT_KIND_RESPONSE)
            _append_text_unit(
                timeline,
                kind=kind,
                origin=role,
                text=content,
                writable=kind in {UNIT_KIND_PROMPT, UNIT_KIND_RESPONSE, UNIT_KIND_OBSERVATION},
                unit_id=f"msg:{message_index}",
                attributes={"role": role},
                metadata={
                    "carrier": "openai_chat_message",
                    "message_index": message_index,
                    "content_mode": "string",
                },
            )
        else:
            blocks = _content_blocks(content)
            for content_index, block in enumerate(blocks):
                block_type = str(block.get("type") or "").strip()
                if block_type in {"text", "input_text", "output_text"}:
                    kind = {
                        "system": UNIT_KIND_INSTRUCTION,
                        "developer": UNIT_KIND_INSTRUCTION,
                        "user": UNIT_KIND_PROMPT,
                        "tool": UNIT_KIND_OBSERVATION,
                    }.get(role, UNIT_KIND_RESPONSE)
                    text = _ensure_text(block.get("text"))
                    _append_text_unit(
                        timeline,
                        kind=kind,
                        origin=role,
                        text=text,
                        writable=kind in {
                            UNIT_KIND_PROMPT,
                            UNIT_KIND_RESPONSE,
                            UNIT_KIND_OBSERVATION,
                        },
                        unit_id=f"msg:{message_index}:part:{content_index}",
                        attributes={"role": role, "contentType": block_type},
                        metadata={
                            "carrier": "openai_chat_message",
                            "message_index": message_index,
                            "content_mode": "list",
                            "content_index": content_index,
                        },
                    )
                    continue
                _append_media_unit(
                    timeline,
                    origin=role,
                    unit_id=f"msg:{message_index}:media:{content_index}",
                    attributes={"role": role, "contentType": block_type, "block": copy.deepcopy(block)},
                    metadata={
                        "carrier": "openai_chat_message",
                        "message_index": message_index,
                        "content_mode": "list",
                        "content_index": content_index,
                    },
                )

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_index, tool_call in enumerate(tool_calls):
                function = tool_call.get("function") if isinstance(tool_call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                arguments = function.get("arguments") if isinstance(function, dict) else None
                timeline.append(
                    SemanticUnit(
                        id=f"msg:{message_index}:tool:{tool_index}",
                        kind=UNIT_KIND_ACTION,
                        origin=role,
                        writable=True,
                        attributes={
                            "role": role,
                            "toolCallId": tool_call.get("id") if isinstance(tool_call, dict) else None,
                            "name": _ensure_text(name),
                            "arguments": _json_arguments(arguments),
                        },
                        metadata={
                            "carrier": "openai_chat_tool_call",
                            "message_index": message_index,
                            "tool_call_index": tool_index,
                        },
                    )
                )
    return timeline


def _normalize_openai_chat_response(body: Dict[str, Any]) -> List[SemanticUnit]:
    timeline: List[SemanticUnit] = []
    choices = body.get("choices")
    if not isinstance(choices, list):
        return timeline
    for choice_index, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            _append_text_unit(
                timeline,
                kind=UNIT_KIND_RESPONSE,
                origin="assistant",
                text=content,
                writable=True,
                unit_id=f"choice:{choice_index}",
                attributes={"choiceIndex": choice_index},
                metadata={
                    "carrier": "openai_chat_response_message",
                    "choice_index": choice_index,
                    "content_mode": "string",
                },
            )
        for content_index, block in enumerate(_content_blocks(content)):
            block_type = str(block.get("type") or "").strip()
            if block_type in {"text", "output_text"}:
                _append_text_unit(
                    timeline,
                    kind=UNIT_KIND_RESPONSE,
                    origin="assistant",
                    text=_ensure_text(block.get("text")),
                    writable=True,
                    unit_id=f"choice:{choice_index}:part:{content_index}",
                    attributes={"choiceIndex": choice_index, "contentType": block_type},
                    metadata={
                        "carrier": "openai_chat_response_message",
                        "choice_index": choice_index,
                        "content_mode": "list",
                        "content_index": content_index,
                    },
                )
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_index, tool_call in enumerate(tool_calls):
                function = tool_call.get("function") if isinstance(tool_call, dict) else None
                timeline.append(
                    SemanticUnit(
                        id=f"choice:{choice_index}:tool:{tool_index}",
                        kind=UNIT_KIND_ACTION,
                        origin="assistant",
                        writable=True,
                        attributes={
                            "choiceIndex": choice_index,
                            "toolCallId": tool_call.get("id") if isinstance(tool_call, dict) else None,
                            "name": _ensure_text(function.get("name") if isinstance(function, dict) else None),
                            "arguments": _json_arguments(function.get("arguments") if isinstance(function, dict) else None),
                        },
                        metadata={
                            "carrier": "openai_chat_response_tool_call",
                            "choice_index": choice_index,
                            "tool_call_index": tool_index,
                        },
                    )
                )
    return timeline


def _normalize_responses_input(input_value: Any) -> List[SemanticUnit]:
    timeline: List[SemanticUnit] = []
    if isinstance(input_value, str):
        _append_text_unit(
            timeline,
            kind=UNIT_KIND_PROMPT,
            origin="user",
            text=input_value,
            writable=True,
            unit_id="input:1",
            attributes={"role": "user"},
            metadata={"carrier": "openai_responses_input_string"},
        )
        return timeline

    items = input_value if isinstance(input_value, list) else [input_value]
    for item_index, item in enumerate(items):
        if isinstance(item, str):
            _append_text_unit(
                timeline,
                kind=UNIT_KIND_PROMPT,
                origin="user",
                text=item,
                writable=True,
                unit_id=f"input:{item_index}",
                attributes={"role": "user"},
                metadata={"carrier": "openai_responses_input_string_item", "item_index": item_index},
            )
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call_output":
            _append_text_unit(
                timeline,
                kind=UNIT_KIND_OBSERVATION,
                origin="tool",
                text=_ensure_text(item.get("output")),
                writable=True,
                unit_id=f"input:{item_index}:observation",
                attributes={
                    "callId": item.get("call_id"),
                    "type": item.get("type"),
                },
                metadata={"carrier": "openai_responses_function_call_output", "item_index": item_index},
            )
            continue
        role = str(item.get("role") or item.get("type") or "user")
        content = item.get("content", item.get("input"))
        if isinstance(content, str):
            kind = UNIT_KIND_INSTRUCTION if role in {"system", "developer"} else UNIT_KIND_PROMPT if role == "user" else UNIT_KIND_RESPONSE
            _append_text_unit(
                timeline,
                kind=kind,
                origin=role,
                text=content,
                writable=kind in {UNIT_KIND_PROMPT, UNIT_KIND_RESPONSE, UNIT_KIND_OBSERVATION},
                unit_id=f"input:{item_index}",
                attributes={"role": role},
                metadata={"carrier": "openai_responses_message", "item_index": item_index, "content_mode": "string"},
            )
            continue
        for content_index, block in enumerate(_content_blocks(content)):
            block_type = str(block.get("type") or "").strip()
            if block_type in {"input_text", "output_text", "text"}:
                kind = UNIT_KIND_INSTRUCTION if role in {"system", "developer"} else UNIT_KIND_PROMPT if role == "user" else UNIT_KIND_RESPONSE
                _append_text_unit(
                    timeline,
                    kind=kind,
                    origin=role,
                    text=_ensure_text(block.get("text")),
                    writable=kind in {UNIT_KIND_PROMPT, UNIT_KIND_RESPONSE, UNIT_KIND_OBSERVATION},
                    unit_id=f"input:{item_index}:part:{content_index}",
                    attributes={"role": role, "contentType": block_type},
                    metadata={"carrier": "openai_responses_message", "item_index": item_index, "content_mode": "list", "content_index": content_index},
                )
                continue
            _append_media_unit(
                timeline,
                origin=role,
                unit_id=f"input:{item_index}:media:{content_index}",
                attributes={"role": role, "contentType": block_type, "block": copy.deepcopy(block)},
                metadata={"carrier": "openai_responses_message", "item_index": item_index, "content_mode": "list", "content_index": content_index},
            )
    return timeline


def _normalize_responses_response(body: Dict[str, Any]) -> List[SemanticUnit]:
    timeline: List[SemanticUnit] = []
    output = body.get("output")
    if isinstance(output, list):
        for item_index, item in enumerate(output):
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip()
            if item_type == "function_call":
                timeline.append(
                    SemanticUnit(
                        id=f"output:{item_index}:action",
                        kind=UNIT_KIND_ACTION,
                        origin="assistant",
                        writable=True,
                        attributes={
                            "name": _ensure_text(item.get("name")),
                            "callId": item.get("call_id"),
                            "arguments": _json_arguments(item.get("arguments")),
                        },
                        metadata={"carrier": "openai_responses_function_call", "item_index": item_index},
                    )
                )
                continue
            if item_type == "function_call_output":
                _append_text_unit(
                    timeline,
                    kind=UNIT_KIND_OBSERVATION,
                    origin="tool",
                    text=_ensure_text(item.get("output")),
                    writable=True,
                    unit_id=f"output:{item_index}:observation",
                    attributes={"callId": item.get("call_id")},
                    metadata={"carrier": "openai_responses_function_call_output", "item_index": item_index},
                )
                continue
            role = str(item.get("role") or "assistant")
            content = item.get("content")
            if isinstance(content, str):
                _append_text_unit(
                    timeline,
                    kind=UNIT_KIND_RESPONSE,
                    origin=role,
                    text=content,
                    writable=True,
                    unit_id=f"output:{item_index}",
                    attributes={"role": role},
                    metadata={"carrier": "openai_responses_output_message", "item_index": item_index, "content_mode": "string"},
                )
                continue
            for content_index, block in enumerate(_content_blocks(content)):
                block_type = str(block.get("type") or "").strip()
                if block_type in {"output_text", "text"}:
                    _append_text_unit(
                        timeline,
                        kind=UNIT_KIND_RESPONSE,
                        origin=role,
                        text=_ensure_text(block.get("text")),
                        writable=True,
                        unit_id=f"output:{item_index}:part:{content_index}",
                        attributes={"role": role, "contentType": block_type},
                        metadata={"carrier": "openai_responses_output_message", "item_index": item_index, "content_mode": "list", "content_index": content_index},
                    )
        if timeline:
            return timeline

    if isinstance(body.get("output_text"), str):
        _append_text_unit(
            timeline,
            kind=UNIT_KIND_RESPONSE,
            origin="assistant",
            text=body["output_text"],
            writable=True,
            unit_id="output_text:1",
            attributes={},
            metadata={"carrier": "openai_responses_output_text"},
        )
    return timeline


def _normalize_anthropic_message_blocks(
    *,
    role: str,
    blocks: Any,
    item_prefix: str,
    message_index: int | None = None,
) -> List[SemanticUnit]:
    timeline: List[SemanticUnit] = []
    if isinstance(blocks, str):
        kind = UNIT_KIND_INSTRUCTION if role == "system" else UNIT_KIND_PROMPT if role == "user" else UNIT_KIND_RESPONSE
        _append_text_unit(
            timeline,
            kind=kind,
            origin=role,
            text=blocks,
            writable=kind in {UNIT_KIND_PROMPT, UNIT_KIND_RESPONSE, UNIT_KIND_OBSERVATION},
            unit_id=item_prefix,
            attributes={"role": role},
            metadata={"carrier": "anthropic_block", "message_index": message_index, "content_mode": "string"},
        )
        return timeline

    for content_index, block in enumerate(_content_blocks(blocks)):
        block_type = str(block.get("type") or "").strip()
        if block_type == "text":
            kind = UNIT_KIND_INSTRUCTION if role == "system" else UNIT_KIND_PROMPT if role == "user" else UNIT_KIND_RESPONSE
            _append_text_unit(
                timeline,
                kind=kind,
                origin=role,
                text=_ensure_text(block.get("text")),
                writable=kind in {UNIT_KIND_PROMPT, UNIT_KIND_RESPONSE, UNIT_KIND_OBSERVATION},
                unit_id=f"{item_prefix}:part:{content_index}",
                attributes={"role": role, "contentType": block_type},
                metadata={"carrier": "anthropic_block", "message_index": message_index, "content_mode": "list", "content_index": content_index},
            )
            continue
        if block_type == "tool_use":
            timeline.append(
                SemanticUnit(
                    id=f"{item_prefix}:action:{content_index}",
                    kind=UNIT_KIND_ACTION,
                    origin=role,
                    writable=True,
                    attributes={
                        "id": block.get("id"),
                        "name": _ensure_text(block.get("name")),
                        "arguments": copy.deepcopy(block.get("input") or {}),
                    },
                    metadata={"carrier": "anthropic_tool_use", "message_index": message_index, "content_index": content_index},
                )
            )
            continue
        if block_type == "tool_result":
            _append_text_unit(
                timeline,
                kind=UNIT_KIND_OBSERVATION,
                origin="tool",
                text=_ensure_text(block.get("content")),
                writable=True,
                unit_id=f"{item_prefix}:observation:{content_index}",
                attributes={"toolUseId": block.get("tool_use_id")},
                metadata={"carrier": "anthropic_tool_result", "message_index": message_index, "content_index": content_index},
            )
            continue
        _append_media_unit(
            timeline,
            origin=role,
            unit_id=f"{item_prefix}:media:{content_index}",
            attributes={"role": role, "contentType": block_type, "block": copy.deepcopy(block)},
            metadata={"carrier": "anthropic_block", "message_index": message_index, "content_index": content_index},
        )
    return timeline


def normalize_request_payload(
    *,
    endpoint_kind: str,
    source: str,
    request_body: Dict[str, Any],
    connector_context: Dict[str, Any] | None = None,
) -> NormalizedPayload:
    native = {
        "request_body": _clone_native(request_body),
    }
    if connector_context:
        native["connector_context"] = _clone_native(connector_context)
    timeline: List[SemanticUnit] = []

    if endpoint_kind == "chat_completions":
        timeline = _normalize_openai_chat_messages(request_body.get("messages") or [])
    elif endpoint_kind == "responses":
        instructions = request_body.get("instructions")
        if isinstance(instructions, str) and instructions:
            _append_text_unit(
                timeline,
                kind=UNIT_KIND_INSTRUCTION,
                origin="source",
                text=instructions,
                writable=False,
                unit_id="instructions:1",
                attributes={},
                metadata={"carrier": "openai_responses_instructions"},
            )
        timeline.extend(_normalize_responses_input(request_body.get("input")))
    elif endpoint_kind == "anthropic_messages":
        system_value = request_body.get("system")
        timeline.extend(
            _normalize_anthropic_message_blocks(
                role="system",
                blocks=system_value,
                item_prefix="system",
            )
        )
        messages = request_body.get("messages")
        if isinstance(messages, list):
            for message_index, message in enumerate(messages):
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or "user")
                timeline.extend(
                    _normalize_anthropic_message_blocks(
                        role=role,
                        blocks=message.get("content"),
                        item_prefix=f"message:{message_index}",
                        message_index=message_index,
                    )
                )
    elif endpoint_kind == "claude_user_prompt":
        _append_text_unit(
            timeline,
            kind=UNIT_KIND_PROMPT,
            origin="user",
            text=_ensure_text(request_body.get("prompt")),
            writable=True,
            unit_id="claude_prompt:1",
            attributes={"sourceEvent": "UserPromptSubmit"},
            metadata={"carrier": "claude_prompt"},
        )
    return NormalizedPayload(
        phase="request",
        endpoint_kind=endpoint_kind,
        source=source,
        timeline=timeline,
        native=native,
        metadata={"connectorContext": _clone_native(connector_context or {})},
    )


def normalize_response_payload(
    *,
    endpoint_kind: str,
    source: str,
    response_body: Dict[str, Any],
    connector_context: Dict[str, Any] | None = None,
) -> NormalizedPayload:
    native = {
        "response_body": _clone_native(response_body),
    }
    if connector_context:
        native["connector_context"] = _clone_native(connector_context)
    timeline: List[SemanticUnit] = []
    if endpoint_kind == "chat_completions":
        timeline = _normalize_openai_chat_response(response_body)
    elif endpoint_kind == "responses":
        timeline = _normalize_responses_response(response_body)
    elif endpoint_kind == "anthropic_messages":
        timeline = _normalize_anthropic_message_blocks(
            role="assistant",
            blocks=response_body.get("content"),
            item_prefix="response",
        )
    elif endpoint_kind == "claude_stop":
        assistant_response = response_body.get("assistant_response")
        if isinstance(assistant_response, str):
            _append_text_unit(
                timeline,
                kind=UNIT_KIND_RESPONSE,
                origin="assistant",
                text=assistant_response,
                writable=True,
                unit_id="claude_response:1",
                attributes={"status": response_body.get("status")},
                metadata={"carrier": "claude_response"},
            )
    return NormalizedPayload(
        phase="response",
        endpoint_kind=endpoint_kind,
        source=source,
        timeline=timeline,
        native=native,
        metadata={"connectorContext": _clone_native(connector_context or {})},
    )


def normalize_stream_event_payload(
    *,
    endpoint_kind: str,
    source: str,
    event: Dict[str, Any],
    request_context: Dict[str, Any] | None = None,
) -> NormalizedPayload:
    native = {
        "event": _clone_native(event),
    }
    if request_context:
        native["request_context"] = _clone_native(request_context)
    timeline: List[SemanticUnit] = []
    if not isinstance(event, dict):
        return NormalizedPayload(
            phase="stream_event",
            endpoint_kind=endpoint_kind,
            source=source,
            timeline=timeline,
            native=native,
        )

    if event.get("data_type") != "json":
        return NormalizedPayload(
            phase="stream_event",
            endpoint_kind=endpoint_kind,
            source=source,
            timeline=timeline,
            native=native,
        )

    payload = event.get("payload")
    if not isinstance(payload, dict):
        return NormalizedPayload(
            phase="stream_event",
            endpoint_kind=endpoint_kind,
            source=source,
            timeline=timeline,
            native=native,
        )

    if endpoint_kind == "chat_completions":
        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice_index, choice in enumerate(choices):
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    continue
                if isinstance(delta.get("content"), str):
                    _append_text_unit(
                        timeline,
                        kind=UNIT_KIND_RESPONSE,
                        origin="assistant",
                        text=delta["content"],
                        writable=True,
                        unit_id=f"stream:choice:{choice_index}:delta",
                        attributes={"choiceIndex": choice_index},
                        metadata={"carrier": "openai_chat_stream_delta", "choice_index": choice_index},
                    )
                tool_calls = delta.get("tool_calls")
                if isinstance(tool_calls, list):
                    for tool_index, tool_call in enumerate(tool_calls):
                        function = tool_call.get("function") if isinstance(tool_call, dict) else None
                        timeline.append(
                            SemanticUnit(
                                id=f"stream:choice:{choice_index}:tool:{tool_index}",
                                kind=UNIT_KIND_ACTION,
                                origin="assistant",
                                writable=True,
                                attributes={
                                    "name": _ensure_text(function.get("name") if isinstance(function, dict) else None),
                                    "arguments": _json_arguments(function.get("arguments") if isinstance(function, dict) else None),
                                },
                                metadata={"carrier": "openai_chat_stream_tool_call", "choice_index": choice_index, "tool_call_index": tool_index},
                            )
                        )
    elif endpoint_kind == "responses":
        event_type = str(payload.get("type") or "").strip()
        if event_type == "response.output_text.delta" and isinstance(payload.get("delta"), str):
            _append_text_unit(
                timeline,
                kind=UNIT_KIND_RESPONSE,
                origin="assistant",
                text=payload["delta"],
                writable=True,
                unit_id="stream:responses:text",
                attributes={"eventType": event_type},
                metadata={"carrier": "openai_responses_stream_text_delta"},
            )
        elif event_type in {"response.output_item.added", "response.output_item.done"}:
            item = payload.get("item")
            if isinstance(item, dict) and item.get("type") == "function_call":
                timeline.append(
                    SemanticUnit(
                        id="stream:responses:action",
                        kind=UNIT_KIND_ACTION,
                        origin="assistant",
                        writable=True,
                        attributes={
                            "name": _ensure_text(item.get("name")),
                            "callId": item.get("call_id"),
                            "arguments": _json_arguments(item.get("arguments")),
                        },
                        metadata={"carrier": "openai_responses_stream_action"},
                    )
                )
    elif endpoint_kind == "anthropic_messages":
        event_name = str(event.get("event_name") or "").strip()
        if event_name == "content_block_delta":
            delta = payload.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("text"), str):
                _append_text_unit(
                    timeline,
                    kind=UNIT_KIND_RESPONSE,
                    origin="assistant",
                    text=delta["text"],
                    writable=True,
                    unit_id="stream:anthropic:text",
                    attributes={"eventName": event_name},
                    metadata={"carrier": "anthropic_stream_text_delta"},
                )
        elif event_name == "content_block_start":
            block = payload.get("content_block")
            if isinstance(block, dict) and block.get("type") == "tool_use":
                timeline.append(
                    SemanticUnit(
                        id="stream:anthropic:action",
                        kind=UNIT_KIND_ACTION,
                        origin="assistant",
                        writable=True,
                        attributes={
                            "id": block.get("id"),
                            "name": _ensure_text(block.get("name")),
                            "arguments": copy.deepcopy(block.get("input") or {}),
                        },
                        metadata={"carrier": "anthropic_stream_action"},
                    )
                )
    return NormalizedPayload(
        phase="stream_event",
        endpoint_kind=endpoint_kind,
        source=source,
        timeline=timeline,
        native=native,
        metadata={"requestContext": _clone_native(request_context or {})},
    )


def _set_openai_message_text(native: Dict[str, Any], metadata: Dict[str, Any], text: str) -> None:
    messages = native.get("messages")
    if not isinstance(messages, list):
        raise PayloadDenormalizationError("openai chat payload is missing messages")
    message_index = metadata.get("message_index")
    if not isinstance(message_index, int) or message_index >= len(messages):
        raise PayloadDenormalizationError("openai chat message index is invalid")
    message = messages[message_index]
    if not isinstance(message, dict):
        raise PayloadDenormalizationError("openai chat message is invalid")
    if metadata.get("content_mode") == "string":
        message["content"] = text
        return
    blocks = message.get("content")
    if not isinstance(blocks, list):
        raise PayloadDenormalizationError("openai chat content blocks are invalid")
    content_index = metadata.get("content_index")
    if not isinstance(content_index, int) or content_index >= len(blocks):
        raise PayloadDenormalizationError("openai chat content index is invalid")
    block = blocks[content_index]
    if not isinstance(block, dict):
        raise PayloadDenormalizationError("openai chat content block is invalid")
    block["text"] = text


def _set_openai_chat_tool_call(native: Dict[str, Any], metadata: Dict[str, Any], attributes: Dict[str, Any]) -> None:
    messages = native.get("messages")
    if not isinstance(messages, list):
        raise PayloadDenormalizationError("openai chat payload is missing messages")
    message_index = metadata.get("message_index")
    tool_index = metadata.get("tool_call_index")
    if not isinstance(message_index, int) or not isinstance(tool_index, int):
        raise PayloadDenormalizationError("openai chat tool metadata is invalid")
    message = messages[message_index]
    tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
    if not isinstance(tool_calls, list) or tool_index >= len(tool_calls):
        raise PayloadDenormalizationError("openai chat tool calls are invalid")
    tool_call = tool_calls[tool_index]
    function = tool_call.setdefault("function", {}) if isinstance(tool_call, dict) else None
    if not isinstance(function, dict):
        raise PayloadDenormalizationError("openai chat tool function is invalid")
    function["name"] = attributes.get("name")
    function["arguments"] = _dump_arguments(attributes.get("arguments"))


def _set_openai_chat_response_text(native: Dict[str, Any], metadata: Dict[str, Any], text: str) -> None:
    choices = native.get("choices")
    if not isinstance(choices, list):
        raise PayloadDenormalizationError("openai response choices are invalid")
    choice_index = metadata.get("choice_index")
    if not isinstance(choice_index, int) or choice_index >= len(choices):
        raise PayloadDenormalizationError("openai response choice index is invalid")
    choice = choices[choice_index]
    message = choice.get("message") if isinstance(choice, dict) else None
    if not isinstance(message, dict):
        raise PayloadDenormalizationError("openai response message is invalid")
    if metadata.get("content_mode") == "string":
        message["content"] = text
        return
    blocks = message.get("content")
    if not isinstance(blocks, list):
        raise PayloadDenormalizationError("openai response content blocks are invalid")
    content_index = metadata.get("content_index")
    if not isinstance(content_index, int) or content_index >= len(blocks):
        raise PayloadDenormalizationError("openai response content index is invalid")
    block = blocks[content_index]
    if not isinstance(block, dict):
        raise PayloadDenormalizationError("openai response content block is invalid")
    block["text"] = text


def _set_openai_chat_response_action(native: Dict[str, Any], metadata: Dict[str, Any], attributes: Dict[str, Any]) -> None:
    choices = native.get("choices")
    if not isinstance(choices, list):
        raise PayloadDenormalizationError("openai response choices are invalid")
    choice_index = metadata.get("choice_index")
    tool_index = metadata.get("tool_call_index")
    if not isinstance(choice_index, int) or not isinstance(tool_index, int):
        raise PayloadDenormalizationError("openai response action metadata is invalid")
    choice = choices[choice_index]
    message = choice.get("message") if isinstance(choice, dict) else None
    tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
    if not isinstance(tool_calls, list) or tool_index >= len(tool_calls):
        raise PayloadDenormalizationError("openai response tool calls are invalid")
    tool_call = tool_calls[tool_index]
    function = tool_call.setdefault("function", {}) if isinstance(tool_call, dict) else None
    if not isinstance(function, dict):
        raise PayloadDenormalizationError("openai response tool function is invalid")
    function["name"] = attributes.get("name")
    function["arguments"] = _dump_arguments(attributes.get("arguments"))


def _set_responses_input(native: Dict[str, Any], metadata: Dict[str, Any], text: str) -> None:
    carrier = metadata.get("carrier")
    if carrier == "openai_responses_input_string":
        native["input"] = text
        return
    input_value = native.get("input")
    if not isinstance(input_value, list):
        raise PayloadDenormalizationError("responses input list is invalid")
    item_index = metadata.get("item_index")
    if not isinstance(item_index, int) or item_index >= len(input_value):
        raise PayloadDenormalizationError("responses input item index is invalid")
    item = input_value[item_index]
    if carrier == "openai_responses_message":
        if metadata.get("content_mode") == "string":
            item["content"] = text
            return
        content = item.get("content")
        if not isinstance(content, list):
            raise PayloadDenormalizationError("responses input content blocks are invalid")
        content_index = metadata.get("content_index")
        if not isinstance(content_index, int) or content_index >= len(content):
            raise PayloadDenormalizationError("responses input content index is invalid")
        block = content[content_index]
        if not isinstance(block, dict):
            raise PayloadDenormalizationError("responses input content block is invalid")
        block["text"] = text
        return
    if carrier == "openai_responses_function_call_output":
        item["output"] = text
        return
    raise PayloadDenormalizationError(f"unsupported responses input carrier '{carrier}'")


def _set_responses_output(native: Dict[str, Any], metadata: Dict[str, Any], text: str) -> None:
    carrier = metadata.get("carrier")
    if carrier == "openai_responses_output_text":
        native["output_text"] = text
        return
    output = native.get("output")
    if not isinstance(output, list):
        raise PayloadDenormalizationError("responses output list is invalid")
    item_index = metadata.get("item_index")
    if not isinstance(item_index, int) or item_index >= len(output):
        raise PayloadDenormalizationError("responses output item index is invalid")
    item = output[item_index]
    if carrier == "openai_responses_output_message":
        if metadata.get("content_mode") == "string":
            item["content"] = text
            return
        content = item.get("content")
        if not isinstance(content, list):
            raise PayloadDenormalizationError("responses output content blocks are invalid")
        content_index = metadata.get("content_index")
        if not isinstance(content_index, int) or content_index >= len(content):
            raise PayloadDenormalizationError("responses output content index is invalid")
        block = content[content_index]
        if not isinstance(block, dict):
            raise PayloadDenormalizationError("responses output content block is invalid")
        block["text"] = text
        return
    if carrier == "openai_responses_function_call_output":
        item["output"] = text
        return
    raise PayloadDenormalizationError(f"unsupported responses output carrier '{carrier}'")


def _set_responses_action(native: Dict[str, Any], metadata: Dict[str, Any], attributes: Dict[str, Any]) -> None:
    output = native.get("output")
    if not isinstance(output, list):
        raise PayloadDenormalizationError("responses output list is invalid")
    item_index = metadata.get("item_index")
    if not isinstance(item_index, int) or item_index >= len(output):
        raise PayloadDenormalizationError("responses action index is invalid")
    item = output[item_index]
    if not isinstance(item, dict):
        raise PayloadDenormalizationError("responses action item is invalid")
    item["name"] = attributes.get("name")
    item["arguments"] = _dump_arguments(attributes.get("arguments"))


def _set_anthropic_block(native: Dict[str, Any], metadata: Dict[str, Any], text: str) -> None:
    if metadata.get("message_index") is None:
        carrier_root = native.get("system")
    else:
        messages = native.get("messages")
        message_index = metadata.get("message_index")
        if not isinstance(messages, list) or not isinstance(message_index, int) or message_index >= len(messages):
            raise PayloadDenormalizationError("anthropic message index is invalid")
        message = messages[message_index]
        carrier_root = message.get("content") if isinstance(message, dict) else None
    if metadata.get("content_mode") == "string":
        if metadata.get("message_index") is None:
            native["system"] = text
        else:
            native["messages"][metadata["message_index"]]["content"] = text
        return
    if not isinstance(carrier_root, list):
        raise PayloadDenormalizationError("anthropic block carrier is invalid")
    content_index = metadata.get("content_index")
    if not isinstance(content_index, int) or content_index >= len(carrier_root):
        raise PayloadDenormalizationError("anthropic content index is invalid")
    block = carrier_root[content_index]
    if not isinstance(block, dict):
        raise PayloadDenormalizationError("anthropic content block is invalid")
    block["text"] = text


def _set_anthropic_action(native: Dict[str, Any], metadata: Dict[str, Any], attributes: Dict[str, Any]) -> None:
    message_index = metadata.get("message_index")
    content_index = metadata.get("content_index")
    if message_index is None:
        content = native.get("content")
    else:
        messages = native.get("messages")
        if not isinstance(messages, list) or not isinstance(message_index, int) or message_index >= len(messages):
            raise PayloadDenormalizationError("anthropic action message index is invalid")
        content = messages[message_index].get("content") if isinstance(messages[message_index], dict) else None
    if not isinstance(content, list) or not isinstance(content_index, int) or content_index >= len(content):
        raise PayloadDenormalizationError("anthropic action content index is invalid")
    block = content[content_index]
    if not isinstance(block, dict):
        raise PayloadDenormalizationError("anthropic action block is invalid")
    block["name"] = attributes.get("name")
    block["input"] = copy.deepcopy(attributes.get("arguments") or {})


def denormalize_request_payload(payload: NormalizedPayload) -> Dict[str, Any]:
    native = _clone_native(payload.native.get("request_body") or {})
    for unit in payload.timeline:
        metadata = unit.metadata or {}
        carrier = metadata.get("carrier")
        if carrier == "openai_chat_message":
            if unit.kind in {UNIT_KIND_INSTRUCTION, UNIT_KIND_PROMPT, UNIT_KIND_RESPONSE, UNIT_KIND_OBSERVATION} and unit.text is not None:
                _set_openai_message_text(native, metadata, unit.text)
        elif carrier == "openai_chat_tool_call":
            _set_openai_chat_tool_call(native, metadata, unit.attributes)
        elif carrier in {
            "openai_responses_input_string",
            "openai_responses_input_string_item",
            "openai_responses_message",
            "openai_responses_function_call_output",
        }:
            if unit.text is not None:
                _set_responses_input(native, metadata, unit.text)
        elif carrier == "openai_responses_instructions":
            if unit.text is not None:
                native["instructions"] = unit.text
        elif carrier in {"anthropic_block", "anthropic_tool_result"}:
            if unit.text is not None:
                _set_anthropic_block(native, metadata, unit.text)
        elif carrier == "anthropic_tool_use":
            _set_anthropic_action(native, metadata, unit.attributes)
        elif carrier == "claude_prompt":
            if unit.text is not None:
                native["prompt"] = unit.text
                event = native.get("event")
                if isinstance(event, dict):
                    event["prompt"] = unit.text
        else:
            if carrier and carrier.startswith("openai_chat") or carrier and carrier.startswith("openai_responses") or carrier and carrier.startswith("anthropic") or carrier == "claude_prompt":
                raise PayloadDenormalizationError(f"unsupported request carrier '{carrier}'")

    inserted_contexts = [
        unit for unit in payload.timeline
        if unit.kind == UNIT_KIND_INSTRUCTION and unit.metadata.get("inserted_by") == "semantic_mutation"
    ]
    for unit in inserted_contexts:
        if payload.endpoint_kind == "chat_completions":
            native.setdefault("messages", [])
            messages = native.get("messages")
            if isinstance(messages, list):
                messages.insert(0, {"role": "system", "content": unit.text or ""})
        elif payload.endpoint_kind == "responses":
            existing = native.get("instructions")
            prefix = unit.text or ""
            native["instructions"] = prefix if not existing else f"{prefix}\n{existing}"
        elif payload.endpoint_kind == "anthropic_messages":
            existing = native.get("system")
            prefix = unit.text or ""
            if isinstance(existing, str) and existing:
                native["system"] = f"{prefix}\n{existing}"
            elif existing is None:
                native["system"] = prefix
            else:
                raise PayloadDenormalizationError(
                    "cannot denormalize inserted context into structured anthropic system blocks"
                )
        elif payload.endpoint_kind == "claude_user_prompt":
            prompt = _ensure_text(native.get("prompt"))
            native["prompt"] = f"{unit.text or ''}\n{prompt}" if prompt else (unit.text or "")
            event = native.get("event")
            if isinstance(event, dict):
                event["prompt"] = native["prompt"]
    return native


def denormalize_response_payload(payload: NormalizedPayload) -> Dict[str, Any]:
    native = _clone_native(payload.native.get("response_body") or {})
    for unit in payload.timeline:
        carrier = unit.metadata.get("carrier")
        if carrier in {"openai_chat_response_message"} and unit.text is not None:
            _set_openai_chat_response_text(native, unit.metadata, unit.text)
        elif carrier == "openai_chat_response_tool_call":
            _set_openai_chat_response_action(native, unit.metadata, unit.attributes)
        elif carrier in {
            "openai_responses_output_message",
            "openai_responses_output_text",
            "openai_responses_function_call_output",
        } and unit.text is not None:
            _set_responses_output(native, unit.metadata, unit.text)
        elif carrier == "openai_responses_function_call":
            _set_responses_action(native, unit.metadata, unit.attributes)
        elif carrier in {"anthropic_block", "anthropic_tool_result"} and unit.text is not None:
            _set_anthropic_block(native, unit.metadata, unit.text)
        elif carrier == "anthropic_tool_use":
            _set_anthropic_action(native, unit.metadata, unit.attributes)
        elif carrier == "claude_response" and unit.text is not None:
            native["assistant_response"] = unit.text
            event = native.get("event")
            if isinstance(event, dict):
                event["assistant_response"] = unit.text
    return native


def denormalize_stream_event_payload(payload: NormalizedPayload) -> Dict[str, Any]:
    native = _clone_native(payload.native.get("event") or {})
    for unit in payload.timeline:
        carrier = unit.metadata.get("carrier")
        event_payload = native.get("payload")
        if not isinstance(event_payload, dict):
            raise PayloadDenormalizationError("stream event payload is invalid")
        if carrier == "openai_chat_stream_delta" and unit.text is not None:
            choices = event_payload.get("choices")
            choice_index = unit.metadata.get("choice_index")
            if not isinstance(choices, list) or not isinstance(choice_index, int) or choice_index >= len(choices):
                raise PayloadDenormalizationError("chat stream choice index is invalid")
            choice = choices[choice_index]
            delta = choice.get("delta") if isinstance(choice, dict) else None
            if not isinstance(delta, dict):
                raise PayloadDenormalizationError("chat stream delta is invalid")
            delta["content"] = unit.text
        elif carrier == "openai_chat_stream_tool_call":
            choices = event_payload.get("choices")
            choice_index = unit.metadata.get("choice_index")
            tool_index = unit.metadata.get("tool_call_index")
            if not isinstance(choices, list) or not isinstance(choice_index, int) or choice_index >= len(choices):
                raise PayloadDenormalizationError("chat stream choice index is invalid")
            choice = choices[choice_index]
            delta = choice.get("delta") if isinstance(choice, dict) else None
            tool_calls = delta.get("tool_calls") if isinstance(delta, dict) else None
            if not isinstance(tool_calls, list) or not isinstance(tool_index, int) or tool_index >= len(tool_calls):
                raise PayloadDenormalizationError("chat stream tool call index is invalid")
            tool_call = tool_calls[tool_index]
            function = tool_call.setdefault("function", {}) if isinstance(tool_call, dict) else None
            if not isinstance(function, dict):
                raise PayloadDenormalizationError("chat stream function is invalid")
            function["name"] = unit.attributes.get("name")
            function["arguments"] = _dump_arguments(unit.attributes.get("arguments"))
        elif carrier == "openai_responses_stream_text_delta" and unit.text is not None:
            event_payload["delta"] = unit.text
        elif carrier == "openai_responses_stream_action":
            item = event_payload.get("item")
            if not isinstance(item, dict):
                raise PayloadDenormalizationError("responses stream item is invalid")
            item["name"] = unit.attributes.get("name")
            item["arguments"] = _dump_arguments(unit.attributes.get("arguments"))
        elif carrier == "anthropic_stream_text_delta" and unit.text is not None:
            delta = event_payload.get("delta")
            if not isinstance(delta, dict):
                raise PayloadDenormalizationError("anthropic stream delta is invalid")
            delta["text"] = unit.text
        elif carrier == "anthropic_stream_action":
            block = event_payload.get("content_block")
            if not isinstance(block, dict):
                raise PayloadDenormalizationError("anthropic stream content block is invalid")
            block["name"] = unit.attributes.get("name")
            block["input"] = copy.deepcopy(unit.attributes.get("arguments") or {})
    return native
