#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from modeio_middleware.connectors.client_identity import CLIENT_OPENCODE
from modeio_middleware.core.provider_auth import CredentialResolver

from modeio_middleware.cli.setup_lib.common import read_json_file
from modeio_middleware.core.provider_policy import build_client_gateway_base_url
from modeio_middleware.cli.setup_lib.opencode import (
    _opencode_route_support,
    _resolve_preserved_upstream_base_url,
    apply_opencode_config_file,
    current_opencode_provider_id,
    default_opencode_config_path,
    uninstall_opencode_config_file,
)

from .base import (
    ATTACHMENT_KIND_CONFIG_PATCH,
    AttachResult,
    AttachmentInspection,
    DetachResult,
    HarnessAdapter,
    HarnessAttachRequest,
    HarnessDetachRequest,
    HarnessInspection,
    HarnessSelection,
)

_RESOLVER = CredentialResolver()


class OpenCodeHarnessAdapter(HarnessAdapter):
    harness_name = CLIENT_OPENCODE
    binary_name = "opencode"
    attachment_kind = ATTACHMENT_KIND_CONFIG_PATCH

    def _resolved_config_path(
        self,
        *,
        env: Mapping[str, str] | None,
        os_name: str | None,
        config_path: Path | None,
    ) -> Path:
        if config_path is not None:
            return config_path
        return default_opencode_config_path(os_name=os_name, env=dict(env or {}))

    def inspect_current_state(
        self,
        *,
        env: Mapping[str, str] | None = None,
        os_name: str | None = None,
    ) -> HarnessInspection:
        del os_name
        resolved_env = dict(env or {})
        inspection = _RESOLVER.inspect(client_name=CLIENT_OPENCODE, env=resolved_env)
        payload = inspection.to_public_dict()
        details = dict(payload)
        provider_id = payload.get("providerId")
        model_id = None
        config_path = default_opencode_config_path(env=resolved_env)
        if config_path.exists():
            config = read_json_file(config_path)
            model_name = config.get("model")
            if isinstance(model_name, str) and "/" in model_name:
                provider_id, model_id = model_name.split("/", 1)
        selection = HarnessSelection(
            provider_id=provider_id,
            model_id=model_id,
            api_family=payload.get("apiFamily"),
        )
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
        del shell, models_cache_path
        resolved_env = dict(env or {})
        resolved_path = self._resolved_config_path(
            env=resolved_env,
            os_name=os_name,
            config_path=config_path,
        )
        details: dict[str, Any] = {
            "path": str(resolved_path),
            "configParentWritable": resolved_path.parent.exists() and resolved_path.parent.is_dir(),
        }
        if not resolved_path.exists():
            details["routeSupport"] = {
                "supported": False,
                "reason": "config_not_found",
                "providerId": None,
            }
            return AttachmentInspection(
                harness_name=self.harness_name,
                attachment_kind=self.attachment_kind,
                attached=False,
                managed=False,
                target=None,
                reason="config_not_found",
                details=details,
            )

        config = read_json_file(resolved_path)
        route_support = _opencode_route_support(
            config=config,
            config_path=resolved_path,
            env=resolved_env,
        )
        provider_id = route_support.get("providerId") or current_opencode_provider_id(config)
        if route_support.get("supported") and provider_id:
            original_base_url, _ = _resolve_preserved_upstream_base_url(
                config,
                config_path=resolved_path,
                provider_id=provider_id,
            )
            if not original_base_url:
                route_support = {
                    **route_support,
                    "supported": False,
                    "reason": "missing_upstream_base_url",
                }
        details["routeSupport"] = route_support
        target = (
            build_client_gateway_base_url(
                gateway_base_url,
                "opencode",
                provider_name=provider_id,
            )
            if provider_id
            else None
        )
        attached = False
        current_base_url = None
        provider = config.get("provider", {}).get(provider_id, {}) if provider_id else {}
        options = provider.get("options", {}) if isinstance(provider, dict) else {}
        raw_base_url = options.get("baseURL") if isinstance(options, dict) else None
        if isinstance(raw_base_url, str) and raw_base_url.strip():
            current_base_url = raw_base_url.strip().rstrip("/")
            attached = bool(target) and current_base_url == target and route_support.get(
                "supported"
            ) is True
        managed = resolved_path.with_name(f"{resolved_path.name}.modeio-route.json").exists()
        details["currentBaseUrl"] = current_base_url
        return AttachmentInspection(
            harness_name=self.harness_name,
            attachment_kind=self.attachment_kind,
            attached=attached,
            managed=managed,
            target=target,
            reason=route_support.get("reason") if not attached else None,
            details=details,
        )

    def attach(self, request: HarnessAttachRequest) -> AttachResult:
        resolved_path = self._resolved_config_path(
            env=request.env,
            os_name=request.os_name,
            config_path=request.config_path,
        )
        result = apply_opencode_config_file(
            config_path=resolved_path,
            gateway_base_url=request.gateway_base_url,
            create_if_missing=request.create_if_missing,
            env=dict(request.env or {}),
        )
        return AttachResult(
            harness_name=self.harness_name,
            attachment_kind=self.attachment_kind,
            supported=bool(result.get("supported", True)),
            changed=bool(result.get("changed", False)),
            reason=result.get("reason"),
            details=result,
        )

    def detach(self, request: HarnessDetachRequest) -> DetachResult:
        resolved_path = self._resolved_config_path(
            env=request.env,
            os_name=request.os_name,
            config_path=request.config_path,
        )
        result = uninstall_opencode_config_file(
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
