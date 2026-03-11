#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from modeio_middleware.cli.setup_lib.claude import (
    _is_claude_http_hook_entry,
    apply_claude_settings_file,
    default_claude_settings_path,
    derive_claude_hook_url,
    uninstall_claude_settings_file,
)
from modeio_middleware.cli.setup_lib.common import read_json_file

from .base import (
    ATTACHMENT_KIND_HOOK_PATCH,
    AttachResult,
    AttachmentInspection,
    DetachResult,
    HarnessAdapter,
    HarnessAttachRequest,
    HarnessDetachRequest,
    HarnessInspection,
)


class ClaudeHarnessAdapter(HarnessAdapter):
    harness_name = "claude"
    binary_name = "claude"
    attachment_kind = ATTACHMENT_KIND_HOOK_PATCH

    def _resolved_config_path(self, *, config_path: Path | None) -> Path:
        if config_path is not None:
            return config_path
        return default_claude_settings_path()

    def inspect_current_state(
        self,
        *,
        env: Mapping[str, str] | None = None,
        os_name: str | None = None,
        config_path: Path | None = None,
        models_cache_path: Path | None = None,
    ) -> HarnessInspection:
        del env, os_name, config_path, models_cache_path
        return HarnessInspection(
            harness_name=self.harness_name,
            binary_name=self.binary_name,
            binary_path=self._binary_path(),
            ready=True,
            guaranteed=True,
            strategy="hook",
            reason=None,
            details={},
        )

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
        del env, os_name, shell, models_cache_path
        resolved_path = self._resolved_config_path(config_path=config_path)
        hook_url = derive_claude_hook_url(gateway_base_url)
        details: dict[str, Any] = {
            "path": str(resolved_path),
            "configParentWritable": resolved_path.parent.exists()
            and resolved_path.parent.is_dir(),
            "authCheck": {
                "supported": False,
                "message": "Claude auth is verified by the live smoke command itself; the doctor only checks binary/config readiness.",
            },
        }
        if not resolved_path.exists():
            return AttachmentInspection(
                harness_name=self.harness_name,
                attachment_kind=self.attachment_kind,
                attached=False,
                managed=False,
                target=hook_url,
                reason="config_not_found",
                details=details,
            )
        payload = read_json_file(resolved_path)
        hooks = payload.get("hooks")
        attached = False
        if isinstance(hooks, dict):
            for groups in hooks.values():
                if not isinstance(groups, list):
                    continue
                for group in groups:
                    if not isinstance(group, dict):
                        continue
                    group_hooks = group.get("hooks")
                    if not isinstance(group_hooks, list):
                        continue
                    for hook in group_hooks:
                        if _is_claude_http_hook_entry(
                            hook,
                            hook_url=hook_url,
                            force_remove=False,
                        ):
                            attached = True
                            break
                    if attached:
                        break
                if attached:
                    break
        return AttachmentInspection(
            harness_name=self.harness_name,
            attachment_kind=self.attachment_kind,
            attached=attached,
            managed=attached,
            target=hook_url,
            reason=None if attached else "hook_url_not_found",
            details=details,
        )

    def attach(self, request: HarnessAttachRequest) -> AttachResult:
        resolved_path = self._resolved_config_path(config_path=request.config_path)
        result = apply_claude_settings_file(
            config_path=resolved_path,
            gateway_base_url=request.gateway_base_url,
            create_if_missing=request.create_if_missing,
        )
        return AttachResult(
            harness_name=self.harness_name,
            attachment_kind=self.attachment_kind,
            supported=True,
            changed=bool(result.get("changed", False)),
            reason=result.get("reason"),
            details=result,
        )

    def detach(self, request: HarnessDetachRequest) -> DetachResult:
        resolved_path = self._resolved_config_path(config_path=request.config_path)
        result = uninstall_claude_settings_file(
            config_path=resolved_path,
            gateway_base_url=request.gateway_base_url,
            force_remove=request.force_remove,
        )
        return DetachResult(
            harness_name=self.harness_name,
            attachment_kind=self.attachment_kind,
            changed=bool(result.get("changed", False)),
            reason=result.get("reason"),
            details=result,
        )
