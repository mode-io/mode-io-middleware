#!/usr/bin/env python3

from __future__ import annotations

import copy
from typing import Any, Dict, Iterable, List

from modeio_middleware.core.payload_types import (
    NormalizedPayload,
    SemanticUnit,
    PAYLOAD_VIEW_ACTIONS,
    PAYLOAD_VIEW_INSTRUCTIONS,
    PAYLOAD_VIEW_OBSERVATIONS,
    PAYLOAD_VIEW_PROMPT,
    PAYLOAD_VIEW_RESPONSE,
    next_unit_id,
)

SEMANTIC_OP_PREPEND_TEXT = "prepend_text"
SEMANTIC_OP_APPEND_TEXT = "append_text"
SEMANTIC_OP_REPLACE_TEXT = "replace_text"
SEMANTIC_OP_INSERT_CONTEXT = "insert_context"
SEMANTIC_OP_PATCH_ACTION_ARGS = "patch_action_args"
SEMANTIC_OP_REPLACE_ACTION = "replace_action"
SEMANTIC_OP_REPLACE_OBSERVATION = "replace_observation"

VALID_SEMANTIC_OPS = {
    SEMANTIC_OP_PREPEND_TEXT,
    SEMANTIC_OP_APPEND_TEXT,
    SEMANTIC_OP_REPLACE_TEXT,
    SEMANTIC_OP_INSERT_CONTEXT,
    SEMANTIC_OP_PATCH_ACTION_ARGS,
    SEMANTIC_OP_REPLACE_ACTION,
    SEMANTIC_OP_REPLACE_OBSERVATION,
}

TEXT_VIEWS = {
    PAYLOAD_VIEW_PROMPT,
    PAYLOAD_VIEW_RESPONSE,
    PAYLOAD_VIEW_OBSERVATIONS,
}


class SemanticMutationError(ValueError):
    pass


def normalize_semantic_operations(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SemanticMutationError("field 'operations' must be an array")

    operations: List[Dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise SemanticMutationError(
                f"operation #{index} must be an object"
            )
        op_name = str(item.get("op") or "").strip().lower()
        if op_name not in VALID_SEMANTIC_OPS:
            raise SemanticMutationError(
                f"operation #{index} uses unsupported op '{op_name}'"
            )
        normalized = copy.deepcopy(item)
        normalized["op"] = op_name
        operations.append(normalized)
    return operations


def _resolve_target_unit(
    payload: NormalizedPayload,
    *,
    operation: Dict[str, Any],
    allowed_views: Iterable[str],
) -> SemanticUnit:
    unit_id = operation.get("target_unit_id")
    if isinstance(unit_id, str) and unit_id.strip():
        for unit in payload.timeline:
            if unit.id == unit_id.strip():
                return unit
        raise SemanticMutationError(
            f"semantic operation target unit '{unit_id}' was not found"
        )

    target_view = str(operation.get("target") or "").strip().lower()
    if target_view not in allowed_views:
        raise SemanticMutationError(
            "semantic operation must target one of "
            + ", ".join(sorted(allowed_views))
        )
    candidates = [
        unit for unit in payload.view_units(target_view) if unit.writable
    ]
    if not candidates:
        raise SemanticMutationError(
            f"semantic operation target '{target_view}' has no writable units"
        )
    return candidates[-1]


def _require_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise SemanticMutationError(f"field '{field_name}' must be a string")
    return value


def _apply_text_edit(
    unit: SemanticUnit,
    *,
    operation: Dict[str, Any],
    audit: List[Dict[str, Any]],
) -> None:
    if not unit.writable:
        raise SemanticMutationError(
            f"semantic unit '{unit.id}' is read-only"
        )
    if unit.text is None:
        raise SemanticMutationError(
            f"semantic unit '{unit.id}' does not carry editable text"
        )

    op_name = operation["op"]
    text = _require_text(operation.get("text"), field_name="text")
    before = unit.text
    if op_name == SEMANTIC_OP_PREPEND_TEXT:
        unit.text = text + unit.text
    elif op_name == SEMANTIC_OP_APPEND_TEXT:
        unit.text = unit.text + text
    elif op_name == SEMANTIC_OP_REPLACE_TEXT:
        unit.text = text
    else:
        raise SemanticMutationError(f"unsupported text operation '{op_name}'")

    audit.append(
        {
            "op": op_name,
            "targetUnitId": unit.id,
            "beforeText": before,
            "afterText": unit.text,
        }
    )


def _apply_insert_context(
    payload: NormalizedPayload,
    *,
    operation: Dict[str, Any],
    audit: List[Dict[str, Any]],
) -> None:
    context_text = _require_text(operation.get("text"), field_name="text")
    new_unit = SemanticUnit(
        id=next_unit_id("instruction:", payload.timeline),
        kind="instruction",
        origin=str(operation.get("origin") or "middleware"),
        writable=False,
        text=context_text,
        attributes={
            "inserted": True,
            "label": str(operation.get("label") or "middleware_context"),
        },
        metadata={"inserted_by": "semantic_mutation"},
    )
    prompt_indexes = [
        index for index, unit in enumerate(payload.timeline) if unit.kind == "prompt"
    ]
    insert_at = prompt_indexes[0] if prompt_indexes else 0
    payload.timeline.insert(insert_at, new_unit)
    audit.append(
        {
            "op": SEMANTIC_OP_INSERT_CONTEXT,
            "targetUnitId": new_unit.id,
            "afterText": context_text,
        }
    )


def _apply_patch_action_args(
    unit: SemanticUnit,
    *,
    operation: Dict[str, Any],
    audit: List[Dict[str, Any]],
) -> None:
    if unit.kind != "action":
        raise SemanticMutationError(
            f"semantic unit '{unit.id}' is not an action"
        )
    raw_patch = operation.get("arguments_patch")
    if not isinstance(raw_patch, dict):
        raise SemanticMutationError(
            "field 'arguments_patch' must be an object"
        )
    current = unit.attributes.get("arguments")
    if current is None:
        current = {}
    if not isinstance(current, dict):
        raise SemanticMutationError(
            f"semantic action '{unit.id}' arguments are not patchable"
        )
    before = copy.deepcopy(current)
    current.update(copy.deepcopy(raw_patch))
    unit.attributes["arguments"] = current
    audit.append(
        {
            "op": SEMANTIC_OP_PATCH_ACTION_ARGS,
            "targetUnitId": unit.id,
            "before": before,
            "after": copy.deepcopy(current),
        }
    )


def _apply_replace_action(
    unit: SemanticUnit,
    *,
    operation: Dict[str, Any],
    audit: List[Dict[str, Any]],
) -> None:
    if unit.kind != "action":
        raise SemanticMutationError(
            f"semantic unit '{unit.id}' is not an action"
        )
    replacement = operation.get("action")
    if not isinstance(replacement, dict):
        raise SemanticMutationError("field 'action' must be an object")
    before = copy.deepcopy(unit.attributes)
    unit.attributes = copy.deepcopy(replacement)
    audit.append(
        {
            "op": SEMANTIC_OP_REPLACE_ACTION,
            "targetUnitId": unit.id,
            "before": before,
            "after": copy.deepcopy(unit.attributes),
        }
    )


def _apply_replace_observation(
    unit: SemanticUnit,
    *,
    operation: Dict[str, Any],
    audit: List[Dict[str, Any]],
) -> None:
    if unit.kind != "observation":
        raise SemanticMutationError(
            f"semantic unit '{unit.id}' is not an observation"
        )
    before = {
        "text": unit.text,
        "attributes": copy.deepcopy(unit.attributes),
    }
    if "text" in operation:
        unit.text = _require_text(operation.get("text"), field_name="text")
    if "observation" in operation:
        observation = operation.get("observation")
        if not isinstance(observation, dict):
            raise SemanticMutationError(
                "field 'observation' must be an object"
            )
        unit.attributes = copy.deepcopy(observation)
    audit.append(
        {
            "op": SEMANTIC_OP_REPLACE_OBSERVATION,
            "targetUnitId": unit.id,
            "before": before,
            "after": {
                "text": unit.text,
                "attributes": copy.deepcopy(unit.attributes),
            },
        }
    )


def apply_semantic_operations(
    payload: NormalizedPayload,
    operations: List[Dict[str, Any]],
) -> NormalizedPayload:
    updated = payload.clone()
    rewrites = list(updated.audit.get("rewrites") or [])

    for operation in operations:
        op_name = operation["op"]
        if op_name in {
            SEMANTIC_OP_PREPEND_TEXT,
            SEMANTIC_OP_APPEND_TEXT,
            SEMANTIC_OP_REPLACE_TEXT,
        }:
            unit = _resolve_target_unit(
                updated,
                operation=operation,
                allowed_views=TEXT_VIEWS,
            )
            _apply_text_edit(unit, operation=operation, audit=rewrites)
            continue

        if op_name == SEMANTIC_OP_INSERT_CONTEXT:
            _apply_insert_context(updated, operation=operation, audit=rewrites)
            continue

        if op_name == SEMANTIC_OP_PATCH_ACTION_ARGS:
            unit = _resolve_target_unit(
                updated,
                operation=operation,
                allowed_views={PAYLOAD_VIEW_ACTIONS},
            )
            _apply_patch_action_args(unit, operation=operation, audit=rewrites)
            continue

        if op_name == SEMANTIC_OP_REPLACE_ACTION:
            unit = _resolve_target_unit(
                updated,
                operation=operation,
                allowed_views={PAYLOAD_VIEW_ACTIONS},
            )
            _apply_replace_action(unit, operation=operation, audit=rewrites)
            continue

        if op_name == SEMANTIC_OP_REPLACE_OBSERVATION:
            unit = _resolve_target_unit(
                updated,
                operation=operation,
                allowed_views={PAYLOAD_VIEW_OBSERVATIONS},
            )
            _apply_replace_observation(unit, operation=operation, audit=rewrites)
            continue

        raise SemanticMutationError(f"unsupported semantic op '{op_name}'")

    updated.audit["rewrites"] = rewrites
    return updated
