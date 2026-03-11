#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from modeio_middleware.connectors.client_identity import CLIENT_CODEX
from modeio_middleware.core.provider_auth import CredentialResolver
from modeio_middleware.core.provider_policy import default_provider_family

from .base import (
    ATTACHMENT_KIND_ENV_SESSION,
    AttachResult,
    AttachmentInspection,
    HarnessAdapter,
    HarnessAttachRequest,
    HarnessDetachRequest,
    HarnessInspection,
    HarnessSelection,
)

_RESOLVER = CredentialResolver()


def default_codex_config_path(*, env: Mapping[str, str] | None = None) -> Path:
    resolved_env = dict(env or {})
    home = Path(resolved_env.get("HOME") or Path.home()).expanduser()
    return home / ".codex" / "config.toml"


def codex_gateway_base_url(gateway_base_url: str) -> str:
    normalized = str(gateway_base_url).rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3]
    return normalized + "/clients/codex/v1"


def codex_set_env_command(shell: str, gateway_base_url: str) -> str:
    target = codex_gateway_base_url(gateway_base_url)
    if shell == "powershell":
        return f'$env:OPENAI_BASE_URL = "{target}"'
    if shell == "cmd":
        return f"set OPENAI_BASE_URL={target}"
    if shell == "fish":
        return f'set -x OPENAI_BASE_URL "{target}"'
    return f'export OPENAI_BASE_URL="{target}"'


def codex_unset_env_command(shell: str) -> str:
    if shell == "powershell":
        return "Remove-Item Env:OPENAI_BASE_URL"
    if shell == "cmd":
        return "set OPENAI_BASE_URL="
    if shell == "fish":
        return "set -e OPENAI_BASE_URL"
    return "unset OPENAI_BASE_URL"


class CodexHarnessAdapter(HarnessAdapter):
    harness_name = CLIENT_CODEX
    binary_name = "codex"
    attachment_kind = ATTACHMENT_KIND_ENV_SESSION

    def inspect_current_state(
        self,
        *,
        env: Mapping[str, str] | None = None,
        os_name: str | None = None,
    ) -> HarnessInspection:
        del os_name
        resolved_env = dict(env or {})
        inspection = _RESOLVER.inspect(client_name=CLIENT_CODEX, env=resolved_env)
        payload = inspection.to_public_dict()
        selection = HarnessSelection(
            provider_id=payload.get("providerId"),
            api_family=payload.get("apiFamily")
            or default_provider_family(payload.get("providerId")),
        )
        details = dict(payload)
        return HarnessInspection(
            harness_name=self.harness_name,
            binary_name=self.binary_name,
            binary_path=self._binary_path(),
            ready=inspection.ready,
            guaranteed=inspection.guaranteed,
            strategy=inspection.strategy,
            reason=inspection.reason,
            selection=selection,
            details=details,
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
        del os_name, models_cache_path
        resolved_env = dict(env or {})
        resolved_shell = shell or "bash"
        target = codex_gateway_base_url(gateway_base_url)
        current = str(resolved_env.get("OPENAI_BASE_URL") or "").strip().rstrip("/")
        attached = current == target
        details = {
            "setCommand": codex_set_env_command(resolved_shell, gateway_base_url),
            "unsetCommand": codex_unset_env_command(resolved_shell),
            "configPath": str(config_path or default_codex_config_path(env=resolved_env)),
            "currentBaseUrl": current or None,
        }
        return AttachmentInspection(
            harness_name=self.harness_name,
            attachment_kind=self.attachment_kind,
            attached=attached,
            managed=attached,
            target=target,
            reason=None if attached else ("env_unset" if not current else "env_points_elsewhere"),
            details=details,
        )

    def attach(self, request: HarnessAttachRequest) -> AttachResult:
        attachment = self.inspect_attachment(
            gateway_base_url=request.gateway_base_url,
            env=request.env,
            shell=request.shell,
            config_path=request.config_path,
        )
        return AttachResult(
            harness_name=self.harness_name,
            attachment_kind=self.attachment_kind,
            supported=True,
            changed=False,
            reason=None,
            details=attachment.to_public_payload(),
        )

    def detach(self, request: HarnessDetachRequest) -> DetachResult:
        attachment = self.inspect_attachment(
            gateway_base_url=request.gateway_base_url,
            env=request.env,
            shell=request.shell,
            config_path=request.config_path,
        )
        return DetachResult(
            harness_name=self.harness_name,
            attachment_kind=self.attachment_kind,
            changed=False,
            reason=attachment.reason,
            details=attachment.to_public_payload(),
        )
