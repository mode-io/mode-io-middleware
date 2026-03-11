#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from modeio_middleware.connectors.client_identity import CLIENT_OPENCLAW
from modeio_middleware.core.provider_auth import CredentialResolver

from modeio_middleware.cli.setup_lib.common import read_json_file
from modeio_middleware.cli.setup_lib.openclaw import (
    apply_openclaw_config_file,
    apply_openclaw_models_cache_file,
    default_openclaw_config_path,
    default_openclaw_models_cache_path,
    uninstall_openclaw_config_file,
    uninstall_openclaw_models_cache_file,
)
from modeio_middleware.cli.setup_lib.openclaw_common import _read_route_metadata
from modeio_middleware.cli.setup_lib.openclaw_common import _resolve_existing_primary
from modeio_middleware.cli.setup_lib.openclaw_routes import _resolve_preserve_provider_target

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


class OpenClawHarnessAdapter(HarnessAdapter):
    harness_name = CLIENT_OPENCLAW
    binary_name = "openclaw"
    attachment_kind = ATTACHMENT_KIND_CONFIG_PATCH

    def _inspection_env(
        self,
        *,
        env: Mapping[str, str] | None,
        os_name: str | None,
        config_path: Path | None,
        models_cache_path: Path | None,
    ) -> dict[str, str]:
        resolved_env = dict(env or {})
        resolved_config_path = self._resolved_config_path(
            env=resolved_env,
            os_name=os_name,
            config_path=config_path,
        )
        resolved_models_cache_path = self._resolved_models_cache_path(
            env=resolved_env,
            config_path=resolved_config_path,
            models_cache_path=models_cache_path,
        )
        agent_dir = resolved_models_cache_path.parent
        resolved_env.setdefault("OPENCLAW_CONFIG_PATH", str(resolved_config_path))
        resolved_env.setdefault("OPENCLAW_AGENT_DIR", str(agent_dir))
        resolved_env.setdefault("PI_CODING_AGENT_DIR", str(agent_dir))
        resolved_env.setdefault("OPENCLAW_STATE_DIR", str(resolved_config_path.parent))
        return resolved_env

    def _resolved_config_path(
        self,
        *,
        env: Mapping[str, str] | None,
        os_name: str | None,
        config_path: Path | None,
    ) -> Path:
        if config_path is not None:
            return config_path
        return default_openclaw_config_path(os_name=os_name, env=dict(env or {}))

    def _resolved_models_cache_path(
        self,
        *,
        env: Mapping[str, str] | None,
        config_path: Path,
        models_cache_path: Path | None,
    ) -> Path:
        if models_cache_path is not None:
            return models_cache_path
        return default_openclaw_models_cache_path(config_path=config_path, env=dict(env or {}))

    def inspect_current_state(
        self,
        *,
        env: Mapping[str, str] | None = None,
        os_name: str | None = None,
        config_path: Path | None = None,
        models_cache_path: Path | None = None,
    ) -> HarnessInspection:
        resolved_env = self._inspection_env(
            env=env,
            os_name=os_name,
            config_path=config_path,
            models_cache_path=models_cache_path,
        )
        inspection = _RESOLVER.inspect(client_name=CLIENT_OPENCLAW, env=resolved_env)
        payload = inspection.to_public_dict()
        resolved_config_path = self._resolved_config_path(
            env=resolved_env,
            os_name=os_name,
            config_path=config_path,
        )
        selection = HarnessSelection(
            provider_id=payload.get("providerId"),
            api_family=payload.get("apiFamily"),
            profile_id=payload.get("selectedProfileId"),
        )
        primary_ref = payload.get("primaryRef")
        if not isinstance(primary_ref, str) and resolved_config_path.exists():
            config = read_json_file(resolved_config_path)
            primary_ref = _resolve_existing_primary(config)
        if isinstance(primary_ref, str) and "/" in primary_ref:
            _, model_id = primary_ref.split("/", 1)
            selection = HarnessSelection(
                provider_id=selection.provider_id,
                api_family=selection.api_family,
                profile_id=selection.profile_id,
                model_id=model_id,
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
            details=dict(payload),
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
        del shell
        resolved_env = dict(env or {})
        resolved_config_path = self._resolved_config_path(
            env=resolved_env,
            os_name=os_name,
            config_path=config_path,
        )
        resolved_models_cache_path = self._resolved_models_cache_path(
            env=resolved_env,
            config_path=resolved_config_path,
            models_cache_path=models_cache_path,
        )
        details: dict[str, Any] = {
            "path": str(resolved_config_path),
            "configParentWritable": resolved_config_path.parent.exists()
            and resolved_config_path.parent.is_dir(),
            "modelsCachePath": str(resolved_models_cache_path),
            "modelsCacheParentWritable": resolved_models_cache_path.parent.exists()
            and resolved_models_cache_path.parent.is_dir(),
        }
        if not resolved_config_path.exists():
            details["routeSupport"] = {
                "supported": False,
                "reason": "config_not_found",
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

        openclaw_config = read_json_file(resolved_config_path)
        models_cache = (
            read_json_file(resolved_models_cache_path)
            if resolved_models_cache_path.exists()
            else None
        )
        route_support = _resolve_preserve_provider_target(
            openclaw_config,
            gateway_base_url,
            models_cache_data=models_cache,
            existing_route_metadata=_read_route_metadata(resolved_config_path),
        )
        details["routeSupport"] = route_support
        target = route_support.get("routeBaseUrl")
        current_base_url = None
        provider_key = route_support.get("providerKey")
        providers = openclaw_config.get("models", {}).get("providers", {})
        if isinstance(provider_key, str) and isinstance(providers, dict):
            provider_obj = providers.get(provider_key)
            if isinstance(provider_obj, dict):
                base_value = provider_obj.get("baseUrl")
                if isinstance(base_value, str) and base_value.strip():
                    current_base_url = base_value.strip().rstrip("/")
        attached = bool(target) and current_base_url == target and route_support.get("supported") is True
        managed = resolved_config_path.with_name(f"{resolved_config_path.name}.modeio-route.json").exists()
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
        resolved_config_path = self._resolved_config_path(
            env=request.env,
            os_name=request.os_name,
            config_path=request.config_path,
        )
        resolved_models_cache_path = self._resolved_models_cache_path(
            env=request.env,
            config_path=resolved_config_path,
            models_cache_path=request.models_cache_path,
        )
        openclaw_report = apply_openclaw_config_file(
            config_path=resolved_config_path,
            gateway_base_url=request.gateway_base_url,
            create_if_missing=request.create_if_missing,
            models_cache_path=resolved_models_cache_path,
        )
        if openclaw_report.get("supported") is True:
            openclaw_report["modelsCache"] = apply_openclaw_models_cache_file(
                models_cache_path=resolved_models_cache_path,
                gateway_base_url=request.gateway_base_url,
                config_path=resolved_config_path,
            )
        else:
            openclaw_report["modelsCache"] = {
                "path": str(resolved_models_cache_path),
                "changed": False,
                "created": False,
                "backupPath": None,
                "reason": "config_route_unsupported",
                "routeMode": "preserve_provider",
            }
        changed = bool(openclaw_report.get("changed", False)) or bool(
            (openclaw_report.get("modelsCache") or {}).get("changed", False)
        )
        return AttachResult(
            harness_name=self.harness_name,
            attachment_kind=self.attachment_kind,
            supported=bool(openclaw_report.get("supported", True)),
            changed=changed,
            reason=openclaw_report.get("reason"),
            details=openclaw_report,
        )

    def detach(self, request: HarnessDetachRequest) -> DetachResult:
        resolved_config_path = self._resolved_config_path(
            env=request.env,
            os_name=request.os_name,
            config_path=request.config_path,
        )
        resolved_models_cache_path = self._resolved_models_cache_path(
            env=request.env,
            config_path=resolved_config_path,
            models_cache_path=request.models_cache_path,
        )
        models_cache_report = uninstall_openclaw_models_cache_file(
            models_cache_path=resolved_models_cache_path,
            gateway_base_url=request.gateway_base_url,
            config_path=resolved_config_path,
            force_remove=request.force_remove,
        )
        openclaw_report = uninstall_openclaw_config_file(
            config_path=resolved_config_path,
            gateway_base_url=request.gateway_base_url,
            force_remove=request.force_remove,
        )
        openclaw_report["modelsCache"] = models_cache_report
        changed = bool(openclaw_report.get("changed", False)) or bool(
            (models_cache_report or {}).get("changed", False)
        )
        return DetachResult(
            harness_name=self.harness_name,
            attachment_kind=self.attachment_kind,
            changed=changed,
            reason=openclaw_report.get("reason"),
            details=openclaw_report,
        )
