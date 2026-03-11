#!/usr/bin/env python3

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

ATTACHMENT_KIND_CONFIG_PATCH = "config_patch"
ATTACHMENT_KIND_ENV_SESSION = "env_session"
ATTACHMENT_KIND_HOOK_PATCH = "hook_patch"
ATTACHMENT_KIND_UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class HarnessSelection:
    provider_id: str | None = None
    model_id: str | None = None
    api_family: str | None = None
    profile_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.provider_id:
            payload["providerId"] = self.provider_id
        if self.model_id:
            payload["modelId"] = self.model_id
        if self.api_family:
            payload["apiFamily"] = self.api_family
        if self.profile_id:
            payload["profileId"] = self.profile_id
        return payload


@dataclass(frozen=True)
class HarnessInspection:
    harness_name: str
    binary_name: str
    ready: bool
    guaranteed: bool
    strategy: str | None
    reason: str | None
    selection: HarnessSelection = field(default_factory=HarnessSelection)
    binary_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def binary_found(self) -> bool:
        return bool(self.binary_path)

    def to_public_payload(self) -> dict[str, Any]:
        payload = {
            "ready": self.ready,
            "guaranteed": self.guaranteed,
            "strategy": self.strategy,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.binary_path:
            payload["binaryPath"] = self.binary_path
        payload.update(self.selection.to_payload())
        payload.update(self.details)
        return payload


@dataclass(frozen=True)
class AttachmentInspection:
    harness_name: str
    attachment_kind: str
    attached: bool
    managed: bool
    target: str | None = None
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_public_payload(self) -> dict[str, Any]:
        payload = {
            "attached": self.attached,
            "managed": self.managed,
            "attachmentKind": self.attachment_kind,
        }
        if self.target:
            payload["target"] = self.target
        if self.reason is not None:
            payload["reason"] = self.reason
        payload.update(self.details)
        return payload


@dataclass(frozen=True)
class HarnessAttachRequest:
    gateway_base_url: str
    env: Mapping[str, str] = field(default_factory=dict)
    os_name: str | None = None
    shell: str | None = None
    config_path: Path | None = None
    models_cache_path: Path | None = None
    create_if_missing: bool = False


@dataclass(frozen=True)
class HarnessDetachRequest:
    gateway_base_url: str
    env: Mapping[str, str] = field(default_factory=dict)
    os_name: str | None = None
    shell: str | None = None
    config_path: Path | None = None
    models_cache_path: Path | None = None
    force_remove: bool = False


@dataclass(frozen=True)
class AttachResult:
    harness_name: str
    attachment_kind: str
    supported: bool
    changed: bool
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetachResult:
    harness_name: str
    attachment_kind: str
    changed: bool
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class HarnessAdapter(ABC):
    harness_name: str
    binary_name: str
    attachment_kind: str

    def _binary_path(self) -> str | None:
        return shutil.which(self.binary_name)

    @abstractmethod
    def inspect_current_state(
        self,
        *,
        env: Mapping[str, str] | None = None,
        os_name: str | None = None,
    ) -> HarnessInspection:
        raise NotImplementedError

    @abstractmethod
    def inspect_attachment(
        self,
        *,
        gateway_base_url: str,
        env: Mapping[str, str] | None = None,
        os_name: str | None = None,
        shell: str | None = None,
        config_path: Path | None = None,
        models_cache_path: Path | None = None,
    ) -> AttachmentInspection:
        raise NotImplementedError

    @abstractmethod
    def attach(self, request: HarnessAttachRequest) -> AttachResult:
        raise NotImplementedError

    @abstractmethod
    def detach(self, request: HarnessDetachRequest) -> DetachResult:
        raise NotImplementedError
