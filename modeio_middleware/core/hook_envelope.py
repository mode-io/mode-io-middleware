#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class HookEnvelope:
    request_id: str
    endpoint_kind: str
    profile: str
    plugin_config: Dict[str, Any]
    shared_state: Dict[str, Any]
    plugin_state: Dict[str, Any]
    services: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None
    request_context: Optional[Dict[str, Any]] = None
    response_context: Optional[Dict[str, Any]] = None
    request_body: Optional[Dict[str, Any]] = None
    request_headers: Optional[Dict[str, str]] = None
    response_body: Optional[Dict[str, Any]] = None
    response_headers: Optional[Dict[str, str]] = None
    event: Optional[Dict[str, Any]] = None
    source: Any = None
    source_event: Any = None
    surface_capabilities: Any = None
    native_event: Any = None

    def _shared_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "request_id": self.request_id,
            "endpoint_kind": self.endpoint_kind,
            "profile": self.profile,
            "plugin_config": self.plugin_config,
            "plugin_state": self.plugin_state,
        }

        if self.context is not None:
            payload["context"] = self.context
        if self.request_context is not None:
            payload["request_context"] = self.request_context
        if self.context is None and self.request_context is not None:
            payload["context"] = self.request_context
        if self.request_context is None and self.context is not None:
            payload["request_context"] = self.context

        if self.response_context is not None:
            payload["response_context"] = self.response_context
        if self.request_body is not None:
            payload["request_body"] = self.request_body
        if self.request_headers is not None:
            payload["request_headers"] = self.request_headers
        if self.response_body is not None:
            payload["response_body"] = self.response_body
        if self.response_headers is not None:
            payload["response_headers"] = self.response_headers
        if self.event is not None:
            payload["event"] = self.event

        for key in (
            "source",
            "source_event",
            "surface_capabilities",
            "native_event",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value

        return payload

    def to_inprocess_input(self) -> Dict[str, Any]:
        payload = self._shared_payload()
        payload["state"] = self.shared_state
        payload["services"] = self.services
        return payload

    def to_protocol_input(self) -> Dict[str, Any]:
        return self._shared_payload()
