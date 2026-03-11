#!/usr/bin/env python3

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

PAYLOAD_VIEW_INSTRUCTIONS = "instructions"
PAYLOAD_VIEW_PROMPT = "prompt"
PAYLOAD_VIEW_ACTIONS = "actions"
PAYLOAD_VIEW_OBSERVATIONS = "observations"
PAYLOAD_VIEW_RESPONSE = "response"

PAYLOAD_VIEWS = (
    PAYLOAD_VIEW_INSTRUCTIONS,
    PAYLOAD_VIEW_PROMPT,
    PAYLOAD_VIEW_ACTIONS,
    PAYLOAD_VIEW_OBSERVATIONS,
    PAYLOAD_VIEW_RESPONSE,
)

UNIT_KIND_INSTRUCTION = "instruction"
UNIT_KIND_PROMPT = "prompt"
UNIT_KIND_ACTION = "action"
UNIT_KIND_OBSERVATION = "observation"
UNIT_KIND_RESPONSE = "response"
UNIT_KIND_MEDIA_REF = "media_ref"

UNIT_KIND_TO_VIEW = {
    UNIT_KIND_INSTRUCTION: PAYLOAD_VIEW_INSTRUCTIONS,
    UNIT_KIND_PROMPT: PAYLOAD_VIEW_PROMPT,
    UNIT_KIND_ACTION: PAYLOAD_VIEW_ACTIONS,
    UNIT_KIND_OBSERVATION: PAYLOAD_VIEW_OBSERVATIONS,
    UNIT_KIND_RESPONSE: PAYLOAD_VIEW_RESPONSE,
}


def _deepcopy_dict(value: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(value) if value else {}


@dataclass
class SemanticUnit:
    id: str
    kind: str
    origin: str
    writable: bool
    text: str | None = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def clone(self) -> "SemanticUnit":
        return SemanticUnit(
            id=self.id,
            kind=self.kind,
            origin=self.origin,
            writable=self.writable,
            text=self.text,
            attributes=_deepcopy_dict(self.attributes),
            metadata=_deepcopy_dict(self.metadata),
        )

    def to_public_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "origin": self.origin,
            "writable": self.writable,
        }
        if self.text is not None:
            payload["text"] = self.text
        if self.attributes:
            payload["attributes"] = _deepcopy_dict(self.attributes)
        if self.metadata:
            payload["metadata"] = _deepcopy_dict(self.metadata)
        return payload

    @classmethod
    def from_public_dict(cls, raw: Dict[str, Any]) -> "SemanticUnit":
        return cls(
            id=str(raw.get("id") or "").strip(),
            kind=str(raw.get("kind") or "").strip(),
            origin=str(raw.get("origin") or "").strip(),
            writable=bool(raw.get("writable", False)),
            text=raw.get("text") if isinstance(raw.get("text"), str) else None,
            attributes=_deepcopy_dict(raw.get("attributes") or {}),
            metadata=_deepcopy_dict(raw.get("metadata") or {}),
        )


@dataclass
class NormalizedPayload:
    phase: str
    endpoint_kind: str
    source: str
    timeline: List[SemanticUnit] = field(default_factory=list)
    native: Dict[str, Any] = field(default_factory=dict)
    audit: Dict[str, Any] = field(
        default_factory=lambda: {
            "rewrites": [],
            "degraded": [],
            "denormalization": [],
        }
    )
    metadata: Dict[str, Any] = field(default_factory=dict)

    def clone(self) -> "NormalizedPayload":
        return NormalizedPayload(
            phase=self.phase,
            endpoint_kind=self.endpoint_kind,
            source=self.source,
            timeline=[unit.clone() for unit in self.timeline],
            native=_deepcopy_dict(self.native),
            audit=_deepcopy_dict(self.audit),
            metadata=_deepcopy_dict(self.metadata),
        )

    def view_units(self, view_name: str) -> List[SemanticUnit]:
        return [
            unit
            for unit in self.timeline
            if UNIT_KIND_TO_VIEW.get(unit.kind) == view_name
        ]

    def build_views(self) -> Dict[str, Dict[str, Any]]:
        views: Dict[str, Dict[str, Any]] = {}
        for view_name in PAYLOAD_VIEWS:
            units = [unit.to_public_dict() for unit in self.view_units(view_name)]
            text_segments = [
                unit.get("text", "")
                for unit in units
                if isinstance(unit.get("text"), str) and unit.get("text")
            ]
            view_payload: Dict[str, Any] = {
                "units": units,
                "count": len(units),
            }
            if text_segments:
                view_payload["text"] = "\n".join(text_segments)
            views[view_name] = view_payload
        return views

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "endpointKind": self.endpoint_kind,
            "source": self.source,
            "timeline": [unit.to_public_dict() for unit in self.timeline],
            "views": self.build_views(),
            "audit": _deepcopy_dict(self.audit),
            "native": _deepcopy_dict(self.native),
            "metadata": _deepcopy_dict(self.metadata),
        }

    @classmethod
    def from_public_dict(cls, raw: Dict[str, Any]) -> "NormalizedPayload":
        timeline_raw = raw.get("timeline")
        timeline = []
        if isinstance(timeline_raw, list):
            for item in timeline_raw:
                if isinstance(item, dict):
                    timeline.append(SemanticUnit.from_public_dict(item))
        return cls(
            phase=str(raw.get("phase") or "").strip(),
            endpoint_kind=str(raw.get("endpointKind") or "").strip(),
            source=str(raw.get("source") or "").strip(),
            timeline=timeline,
            native=_deepcopy_dict(raw.get("native") or {}),
            audit=_deepcopy_dict(raw.get("audit") or {}),
            metadata=_deepcopy_dict(raw.get("metadata") or {}),
        )


def next_unit_id(prefix: str, existing_units: Iterable[SemanticUnit]) -> str:
    count = 0
    for unit in existing_units:
        if unit.id.startswith(prefix):
            count += 1
    return f"{prefix}{count + 1}"
