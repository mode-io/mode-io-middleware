#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from modeio_middleware.cli.setup_lib.common import utc_timestamp
from modeio_middleware.runtime_home import default_modeio_config_path

CONTROLLER_STATE_VERSION = 1
DEFAULT_CONTROLLER_HOST = "127.0.0.1"
DEFAULT_CONTROLLER_PORT = 8787


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> Dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object in {path}")
    return parsed


@dataclass(frozen=True)
class EnabledHarnessRecord:
    harness_name: str
    attachment_kind: str
    enabled_at: str
    path_overrides: Dict[str, str] = field(default_factory=dict)
    last_inspection: Dict[str, Any] = field(default_factory=dict)
    last_attachment: Dict[str, Any] = field(default_factory=dict)
    last_selection: Dict[str, Any] = field(default_factory=dict)
    last_reason: str | None = None

    @classmethod
    def from_payload(cls, harness_name: str, payload: Dict[str, Any]) -> "EnabledHarnessRecord":
        return cls(
            harness_name=harness_name,
            attachment_kind=str(payload.get("attachmentKind") or ""),
            enabled_at=str(payload.get("enabledAt") or ""),
            path_overrides=dict(payload.get("pathOverrides") or {}),
            last_inspection=dict(payload.get("lastInspection") or {}),
            last_attachment=dict(payload.get("lastAttachment") or {}),
            last_selection=dict(payload.get("lastSelection") or {}),
            last_reason=payload.get("lastReason"),
        )

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "attachmentKind": self.attachment_kind,
            "enabledAt": self.enabled_at,
            "pathOverrides": dict(self.path_overrides),
            "lastInspection": dict(self.last_inspection),
            "lastAttachment": dict(self.last_attachment),
            "lastSelection": dict(self.last_selection),
        }
        if self.last_reason is not None:
            payload["lastReason"] = self.last_reason
        return payload


@dataclass(frozen=True)
class ControllerState:
    version: int = CONTROLLER_STATE_VERSION
    host: str = DEFAULT_CONTROLLER_HOST
    port: int = DEFAULT_CONTROLLER_PORT
    allow_remote_admin: bool = False
    enabled_harnesses: Dict[str, EnabledHarnessRecord] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "ControllerState":
        enabled_payload = payload.get("enabledHarnesses") or {}
        enabled_harnesses: Dict[str, EnabledHarnessRecord] = {}
        if isinstance(enabled_payload, dict):
            for harness_name, item in enabled_payload.items():
                if isinstance(item, dict):
                    enabled_harnesses[harness_name] = EnabledHarnessRecord.from_payload(
                        harness_name,
                        item,
                    )
        return cls(
            version=int(payload.get("version") or CONTROLLER_STATE_VERSION),
            host=str(payload.get("host") or DEFAULT_CONTROLLER_HOST),
            port=int(payload.get("port") or DEFAULT_CONTROLLER_PORT),
            allow_remote_admin=bool(payload.get("allowRemoteAdmin", False)),
            enabled_harnesses=enabled_harnesses,
        )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "host": self.host,
            "port": self.port,
            "allowRemoteAdmin": self.allow_remote_admin,
            "enabledHarnesses": {
                harness_name: record.to_payload()
                for harness_name, record in sorted(self.enabled_harnesses.items())
            },
        }

    def with_server(self, *, host: str, port: int, allow_remote_admin: bool) -> "ControllerState":
        return ControllerState(
            version=self.version,
            host=host,
            port=port,
            allow_remote_admin=allow_remote_admin,
            enabled_harnesses=dict(self.enabled_harnesses),
        )

    def with_enabled_record(self, record: EnabledHarnessRecord) -> "ControllerState":
        enabled = dict(self.enabled_harnesses)
        enabled[record.harness_name] = record
        return ControllerState(
            version=self.version,
            host=self.host,
            port=self.port,
            allow_remote_admin=self.allow_remote_admin,
            enabled_harnesses=enabled,
        )

    def without_enabled_record(self, harness_name: str) -> "ControllerState":
        enabled = dict(self.enabled_harnesses)
        enabled.pop(harness_name, None)
        return ControllerState(
            version=self.version,
            host=self.host,
            port=self.port,
            allow_remote_admin=self.allow_remote_admin,
            enabled_harnesses=enabled,
        )


def default_controller_state_path(*, config_path: Path | None = None) -> Path:
    resolved_config_path = config_path.expanduser() if config_path is not None else default_modeio_config_path()
    return resolved_config_path.parent / "controller.json"


def default_controller_pid_path(*, config_path: Path | None = None) -> Path:
    resolved_config_path = config_path.expanduser() if config_path is not None else default_modeio_config_path()
    return resolved_config_path.parent / "controller.pid"


def default_controller_log_path(*, config_path: Path | None = None) -> Path:
    resolved_config_path = config_path.expanduser() if config_path is not None else default_modeio_config_path()
    return resolved_config_path.parent / "controller.log"


class ControllerStateStore:
    def __init__(self, *, config_path: Path | None = None) -> None:
        self.config_path = config_path.expanduser() if config_path is not None else default_modeio_config_path()
        self.state_path = default_controller_state_path(config_path=self.config_path)
        self.pid_path = default_controller_pid_path(config_path=self.config_path)
        self.log_path = default_controller_log_path(config_path=self.config_path)

    def load(self) -> ControllerState:
        if not self.state_path.exists():
            return ControllerState()
        payload = _read_json(self.state_path)
        return ControllerState.from_payload(payload)

    def save(self, state: ControllerState) -> None:
        _atomic_write_json(self.state_path, state.to_payload())

    def load_pid_payload(self) -> Dict[str, Any] | None:
        if not self.pid_path.exists():
            return None
        return _read_json(self.pid_path)

    def save_pid_payload(self, payload: Dict[str, Any]) -> None:
        _atomic_write_json(self.pid_path, payload)

    def clear_pid_payload(self) -> None:
        try:
            self.pid_path.unlink()
        except FileNotFoundError:
            return

    @staticmethod
    def build_enabled_record(
        *,
        harness_name: str,
        attachment_kind: str,
        path_overrides: Dict[str, str],
        last_inspection: Dict[str, Any],
        last_attachment: Dict[str, Any],
        last_selection: Dict[str, Any],
        last_reason: str | None,
    ) -> EnabledHarnessRecord:
        return EnabledHarnessRecord(
            harness_name=harness_name,
            attachment_kind=attachment_kind,
            enabled_at=utc_timestamp(),
            path_overrides=path_overrides,
            last_inspection=last_inspection,
            last_attachment=last_attachment,
            last_selection=last_selection,
            last_reason=last_reason,
        )
