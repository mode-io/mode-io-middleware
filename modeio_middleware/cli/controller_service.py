#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping

from .controller_process import ControllerProcessError, GatewayProcessManager
from .controller_state import (
    DEFAULT_CONTROLLER_HOST,
    DEFAULT_CONTROLLER_PORT,
    ControllerState,
    ControllerStateStore,
    EnabledHarnessRecord,
)
from .harness_adapters import (
    AttachResult,
    HarnessAdapter,
    HarnessAdapterRegistry,
    HarnessAttachRequest,
    HarnessDetachRequest,
    HarnessInspection,
)


@dataclass(frozen=True)
class HarnessPathOverrides:
    config_path: Path | None = None
    models_cache_path: Path | None = None

    def to_payload(self) -> Dict[str, str]:
        payload: Dict[str, str] = {}
        if self.config_path is not None:
            payload["configPath"] = str(self.config_path)
        if self.models_cache_path is not None:
            payload["modelsCachePath"] = str(self.models_cache_path)
        return payload


class ControllerService:
    def __init__(self, *, state_store: ControllerStateStore, registry: HarnessAdapterRegistry | None = None) -> None:
        self._state_store = state_store
        self._registry = registry or HarnessAdapterRegistry()
        self._process_manager = GatewayProcessManager(state_store=state_store)

    def _normalize_harness_name(self, harness_name: str) -> str:
        return self._registry.normalize_name(harness_name)

    def _base_url(self, *, host: str, port: int) -> str:
        return f"http://{host}:{port}/v1"

    def _resolve_server_settings(
        self,
        state: ControllerState,
        *,
        host: str | None = None,
        port: int | None = None,
        allow_remote_admin: bool | None = None,
    ) -> tuple[str, int, bool]:
        return (
            host or state.host or DEFAULT_CONTROLLER_HOST,
            port or state.port or DEFAULT_CONTROLLER_PORT,
            state.allow_remote_admin if allow_remote_admin is None else allow_remote_admin,
        )

    def _build_attach_request(
        self,
        *,
        gateway_base_url: str,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
        overrides: HarnessPathOverrides,
    ) -> HarnessAttachRequest:
        return HarnessAttachRequest(
            gateway_base_url=gateway_base_url,
            env=env,
            os_name=os_name,
            shell=shell,
            config_path=overrides.config_path,
            models_cache_path=overrides.models_cache_path,
            create_if_missing=True,
        )

    def _build_detach_request(
        self,
        *,
        gateway_base_url: str,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
        overrides: HarnessPathOverrides,
        force_remove: bool = False,
    ) -> HarnessDetachRequest:
        return HarnessDetachRequest(
            gateway_base_url=gateway_base_url,
            env=env,
            os_name=os_name,
            shell=shell,
            config_path=overrides.config_path,
            models_cache_path=overrides.models_cache_path,
            force_remove=force_remove,
        )

    def _controller_support(
        self,
        adapter: HarnessAdapter,
        inspection: HarnessInspection,
    ) -> tuple[bool, str | None]:
        if not getattr(adapter, "controller_supported", True):
            return False, adapter.controller_support_reason()
        if not inspection.ready:
            return False, inspection.reason or "current harness state is not supported"
        return True, None

    def _inspect_one(
        self,
        *,
        adapter: HarnessAdapter,
        gateway_base_url: str,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
        overrides: HarnessPathOverrides,
        enabled_record: EnabledHarnessRecord | None,
    ) -> Dict[str, Any]:
        inspection = adapter.inspect_current_state(
            env=env,
            os_name=os_name,
            config_path=overrides.config_path,
            models_cache_path=overrides.models_cache_path,
        )
        controller_supported, controller_reason = self._controller_support(
            adapter,
            inspection,
        )
        attachment = adapter.inspect_attachment(
            gateway_base_url=gateway_base_url,
            env=env,
            os_name=os_name,
            shell=shell,
            config_path=overrides.config_path,
            models_cache_path=overrides.models_cache_path,
        )
        selection_payload = inspection.selection.to_payload()
        payload: Dict[str, Any] = {
            "harness": adapter.harness_name,
            "controllerSupported": controller_supported,
            "supported": controller_supported,
            "enabled": enabled_record is not None,
            "inspection": inspection.to_public_payload(),
            "attachment": attachment.to_public_payload(),
            "selection": selection_payload,
        }
        if controller_reason is not None:
            payload["reason"] = controller_reason
        elif inspection.reason is not None:
            payload["reason"] = inspection.reason
        elif attachment.reason is not None and not attachment.attached:
            payload["reason"] = attachment.reason
        if enabled_record is not None:
            payload["enabledAt"] = enabled_record.enabled_at
            payload["pathOverrides"] = dict(enabled_record.path_overrides)
        return payload

    def inspect(
        self,
        *,
        harness_name: str | None,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
        host: str | None = None,
        port: int | None = None,
        allow_remote_admin: bool | None = None,
        overrides: Dict[str, HarnessPathOverrides] | None = None,
    ) -> Dict[str, Any]:
        state = self._state_store.load()
        resolved_host, resolved_port, resolved_allow_remote_admin = self._resolve_server_settings(
            state,
            host=host,
            port=port,
            allow_remote_admin=allow_remote_admin,
        )
        gateway_base_url = self._base_url(host=resolved_host, port=resolved_port)
        target_names = (
            (self._normalize_harness_name(harness_name),)
            if harness_name
            else self._registry.adapter_names()
        )
        by_harness: Dict[str, Any] = {}
        overrides_map = overrides or {}
        for name in target_names:
            adapter = self._registry.adapter_for(name)
            enabled_record = state.enabled_harnesses.get(name)
            record_overrides = HarnessPathOverrides(
                config_path=Path(enabled_record.path_overrides["configPath"])
                if enabled_record and enabled_record.path_overrides.get("configPath")
                else None,
                models_cache_path=Path(enabled_record.path_overrides["modelsCachePath"])
                if enabled_record and enabled_record.path_overrides.get("modelsCachePath")
                else None,
            )
            effective_overrides = overrides_map.get(name) or record_overrides
            by_harness[name] = self._inspect_one(
                adapter=adapter,
                gateway_base_url=gateway_base_url,
                env=env,
                os_name=os_name,
                shell=shell,
                overrides=effective_overrides,
                enabled_record=enabled_record,
            )
        return {
            "success": True,
            "server": {
                "host": resolved_host,
                "port": resolved_port,
                "allowRemoteAdmin": resolved_allow_remote_admin,
                "gatewayBaseUrl": gateway_base_url,
                "configPath": str(self._state_store.config_path),
            },
            "harnesses": by_harness,
        }

    def _rollback_attach_results(
        self,
        *,
        changed_harnesses: list[tuple[str, HarnessPathOverrides, bool]],
        current_base_url: str,
        previous_base_url: str,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
    ) -> None:
        for harness_name, overrides, existed_before in reversed(changed_harnesses):
            adapter = self._registry.adapter_for(harness_name)
            if existed_before:
                adapter.attach(
                    self._build_attach_request(
                        gateway_base_url=previous_base_url,
                        env=env,
                        os_name=os_name,
                        shell=shell,
                        overrides=overrides,
                    )
                )
            else:
                adapter.detach(
                    self._build_detach_request(
                        gateway_base_url=current_base_url,
                        env=env,
                        os_name=os_name,
                        shell=shell,
                        overrides=overrides,
                        force_remove=False,
                    )
                )

    def _sync_harness(
        self,
        *,
        harness_name: str,
        gateway_base_url: str,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
        overrides: HarnessPathOverrides,
    ) -> tuple[HarnessInspection, AttachResult]:
        adapter = self._registry.adapter_for(harness_name)
        inspection = adapter.inspect_current_state(
            env=env,
            os_name=os_name,
            config_path=overrides.config_path,
            models_cache_path=overrides.models_cache_path,
        )
        controller_supported, controller_reason = self._controller_support(
            adapter,
            inspection,
        )
        if not controller_supported:
            reason = controller_reason or "current harness state is not supported"
            raise ValueError(reason)
        attach_result = adapter.attach(
            self._build_attach_request(
                gateway_base_url=gateway_base_url,
                env=env,
                os_name=os_name,
                shell=shell,
                overrides=overrides,
            )
        )
        if not attach_result.supported:
            raise ValueError(
                attach_result.reason or "current harness state is not supported"
            )
        return inspection, attach_result

    def enable(
        self,
        *,
        harness_name: str,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
        host: str | None,
        port: int | None,
        allow_remote_admin: bool | None,
        overrides: HarnessPathOverrides,
    ) -> Dict[str, Any]:
        normalized = self._normalize_harness_name(harness_name)
        state = self._state_store.load()
        adapter = self._registry.adapter_for(normalized)
        preview = adapter.inspect_current_state(
            env=env,
            os_name=os_name,
            config_path=overrides.config_path,
            models_cache_path=overrides.models_cache_path,
        )
        controller_supported, controller_reason = self._controller_support(adapter, preview)
        if not controller_supported:
            return {
                "success": False,
                "reason": controller_reason,
                "unsupported": True,
                "harness": normalized,
            }

        resolved_host, resolved_port, resolved_allow_remote_admin = self._resolve_server_settings(
            state,
            host=host,
            port=port,
            allow_remote_admin=allow_remote_admin,
        )
        target_base_url = self._base_url(host=resolved_host, port=resolved_port)
        current_base_url = self._base_url(host=state.host, port=state.port)
        existing_names = list(state.enabled_harnesses.keys())
        existed_before = normalized in state.enabled_harnesses
        sync_names = list(existing_names)
        if normalized not in sync_names:
            sync_names.append(normalized)

        changed_harnesses: list[tuple[str, HarnessPathOverrides, bool]] = []
        synced_results: Dict[str, tuple[HarnessInspection, AttachResult, HarnessPathOverrides]] = {}
        try:
            for name in sync_names:
                record = state.enabled_harnesses.get(name)
                effective_overrides = overrides if name == normalized else HarnessPathOverrides(
                    config_path=Path(record.path_overrides["configPath"])
                    if record and record.path_overrides.get("configPath")
                    else None,
                    models_cache_path=Path(record.path_overrides["modelsCachePath"])
                    if record and record.path_overrides.get("modelsCachePath")
                    else None,
                )
                if name != normalized and target_base_url == current_base_url:
                    continue
                inspection, attach_result = self._sync_harness(
                    harness_name=name,
                    gateway_base_url=target_base_url,
                    env=env,
                    os_name=os_name,
                    shell=shell,
                    overrides=effective_overrides,
                )
                synced_results[name] = (inspection, attach_result, effective_overrides)
                if attach_result.changed:
                    changed_harnesses.append((name, effective_overrides, name in state.enabled_harnesses))

            process_status = self._process_manager.start(
                host=resolved_host,
                port=resolved_port,
                allow_remote_admin=resolved_allow_remote_admin,
            )
        except (ValueError, ControllerProcessError) as error:
            self._rollback_attach_results(
                changed_harnesses=changed_harnesses,
                current_base_url=target_base_url,
                previous_base_url=current_base_url,
                env=env,
                os_name=os_name,
                shell=shell,
            )
            return {
                "success": False,
                "reason": str(error),
                "unsupported": isinstance(error, ValueError),
                "harness": normalized,
            }

        next_state = state.with_server(
            host=resolved_host,
            port=resolved_port,
            allow_remote_admin=resolved_allow_remote_admin,
        )
        for name in sync_names:
            record = state.enabled_harnesses.get(name)
            if name in synced_results:
                inspection, attach_result, effective_overrides = synced_results[name]
                selection_payload = inspection.selection.to_payload()
                next_state = next_state.with_enabled_record(
                    ControllerStateStore.build_enabled_record(
                        harness_name=name,
                        attachment_kind=attach_result.attachment_kind,
                        path_overrides=effective_overrides.to_payload(),
                        last_inspection=inspection.to_public_payload(),
                        last_attachment=dict(attach_result.details),
                        last_selection=selection_payload,
                        last_reason=attach_result.reason,
                    )
                )
                continue
            if record is not None:
                next_state = next_state.with_enabled_record(record)
        self._state_store.save(next_state)
        return {
            "success": True,
            "harness": normalized,
            "enabled": True,
            "server": process_status.to_payload(),
            "inspection": (synced_results.get(normalized) or (preview, None, overrides))[0].to_public_payload(),
            "attachment": dict(
                (synced_results.get(normalized) or (None, None, None))[1].details
            )
            if normalized in synced_results
            else {},
        }

    def disable(
        self,
        *,
        harness_name: str,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
        force_remove: bool = False,
    ) -> Dict[str, Any]:
        normalized = self._normalize_harness_name(harness_name)
        state = self._state_store.load()
        if normalized == "codex":
            return {
                "success": False,
                "reason": self._registry.adapter_for("codex").controller_support_reason(),
                "unsupported": True,
                "harness": "codex",
            }
        record = state.enabled_harnesses.get(normalized)
        if record is None:
            return {
                "success": True,
                "harness": normalized,
                "changed": False,
                "reason": "not_enabled",
            }
        overrides = HarnessPathOverrides(
            config_path=Path(record.path_overrides["configPath"])
            if record.path_overrides.get("configPath")
            else None,
            models_cache_path=Path(record.path_overrides["modelsCachePath"])
            if record.path_overrides.get("modelsCachePath")
            else None,
        )
        adapter = self._registry.adapter_for(normalized)
        base_url = self._base_url(host=state.host, port=state.port)
        detach_result = adapter.detach(
            self._build_detach_request(
                gateway_base_url=base_url,
                env=env,
                os_name=os_name,
                shell=shell,
                overrides=overrides,
                force_remove=force_remove,
            )
        )
        next_state = state.without_enabled_record(normalized)
        self._state_store.save(next_state)
        server_payload = None
        if not next_state.enabled_harnesses:
            server_payload = self._process_manager.stop().to_payload()
        return {
            "success": True,
            "harness": normalized,
            "changed": detach_result.changed,
            "detached": True,
            "server": server_payload,
            "result": detach_result.details,
        }

    def disable_all(
        self,
        *,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
        force_remove: bool = False,
    ) -> Dict[str, Any]:
        state = self._state_store.load()
        base_url = self._base_url(host=state.host, port=state.port)
        results: Dict[str, Any] = {}
        for harness_name, record in list(state.enabled_harnesses.items()):
            if harness_name == "codex":
                continue
            overrides = HarnessPathOverrides(
                config_path=Path(record.path_overrides["configPath"])
                if record.path_overrides.get("configPath")
                else None,
                models_cache_path=Path(record.path_overrides["modelsCachePath"])
                if record.path_overrides.get("modelsCachePath")
                else None,
            )
            detach_result = self._registry.adapter_for(harness_name).detach(
                self._build_detach_request(
                    gateway_base_url=base_url,
                    env=env,
                    os_name=os_name,
                    shell=shell,
                    overrides=overrides,
                    force_remove=force_remove,
                )
            )
            results[harness_name] = detach_result.details
            state = state.without_enabled_record(harness_name)
        self._state_store.save(state)
        server_status = self._process_manager.stop()
        return {
            "success": True,
            "disabledAll": True,
            "harnesses": results,
            "server": server_status.to_payload(),
        }

    def start(
        self,
        *,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
        host: str | None,
        port: int | None,
        allow_remote_admin: bool | None,
    ) -> Dict[str, Any]:
        state = self._state_store.load()
        if not state.enabled_harnesses:
            return {
                "success": False,
                "reason": "no_enabled_harnesses",
            }
        resolved_host, resolved_port, resolved_allow_remote_admin = self._resolve_server_settings(
            state,
            host=host,
            port=port,
            allow_remote_admin=allow_remote_admin,
        )
        target_base_url = self._base_url(host=resolved_host, port=resolved_port)
        current_base_url = self._base_url(host=state.host, port=state.port)
        changed_harnesses: list[tuple[str, HarnessPathOverrides, bool]] = []
        synced_results: Dict[str, tuple[HarnessInspection, AttachResult, HarnessPathOverrides]] = {}
        try:
            for harness_name, record in state.enabled_harnesses.items():
                overrides = HarnessPathOverrides(
                    config_path=Path(record.path_overrides["configPath"])
                    if record.path_overrides.get("configPath")
                    else None,
                    models_cache_path=Path(record.path_overrides["modelsCachePath"])
                    if record.path_overrides.get("modelsCachePath")
                    else None,
                )
                inspection, attach_result = self._sync_harness(
                    harness_name=harness_name,
                    gateway_base_url=target_base_url,
                    env=env,
                    os_name=os_name,
                    shell=shell,
                    overrides=overrides,
                )
                synced_results[harness_name] = (inspection, attach_result, overrides)
                if attach_result.changed:
                    changed_harnesses.append((harness_name, overrides, True))
            process_status = self._process_manager.start(
                host=resolved_host,
                port=resolved_port,
                allow_remote_admin=resolved_allow_remote_admin,
            )
        except (ValueError, ControllerProcessError) as error:
            self._rollback_attach_results(
                changed_harnesses=changed_harnesses,
                current_base_url=target_base_url,
                previous_base_url=current_base_url,
                env=env,
                os_name=os_name,
                shell=shell,
            )
            return {
                "success": False,
                "reason": str(error),
                "unsupported": isinstance(error, ValueError),
            }

        next_state = state.with_server(
            host=resolved_host,
            port=resolved_port,
            allow_remote_admin=resolved_allow_remote_admin,
        )
        for harness_name, (inspection, attach_result, overrides) in synced_results.items():
            next_state = next_state.with_enabled_record(
                ControllerStateStore.build_enabled_record(
                    harness_name=harness_name,
                    attachment_kind=attach_result.attachment_kind,
                    path_overrides=overrides.to_payload(),
                    last_inspection=inspection.to_public_payload(),
                    last_attachment=dict(attach_result.details),
                    last_selection=inspection.selection.to_payload(),
                    last_reason=attach_result.reason,
                )
            )
        self._state_store.save(next_state)
        return {
            "success": True,
            "server": process_status.to_payload(),
            "enabledHarnesses": sorted(next_state.enabled_harnesses),
        }

    def stop(self) -> Dict[str, Any]:
        status = self._process_manager.stop()
        return {
            "success": True,
            "server": status.to_payload(),
        }

    def restart(
        self,
        *,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
        host: str | None,
        port: int | None,
        allow_remote_admin: bool | None,
    ) -> Dict[str, Any]:
        self._process_manager.stop()
        return self.start(
            env=env,
            os_name=os_name,
            shell=shell,
            host=host,
            port=port,
            allow_remote_admin=allow_remote_admin,
        )

    def status(
        self,
        *,
        env: Mapping[str, str],
        os_name: str | None,
        shell: str | None,
    ) -> Dict[str, Any]:
        state = self._state_store.load()
        process_status = self._process_manager.status()
        gateway_base_url = self._base_url(host=state.host, port=state.port)
        harnesses: Dict[str, Any] = {}
        for harness_name, record in state.enabled_harnesses.items():
            overrides = HarnessPathOverrides(
                config_path=Path(record.path_overrides["configPath"])
                if record.path_overrides.get("configPath")
                else None,
                models_cache_path=Path(record.path_overrides["modelsCachePath"])
                if record.path_overrides.get("modelsCachePath")
                else None,
            )
            harnesses[harness_name] = self._inspect_one(
                adapter=self._registry.adapter_for(harness_name),
                gateway_base_url=gateway_base_url,
                env=env,
                os_name=os_name,
                shell=shell,
                overrides=overrides,
                enabled_record=record,
            )
        return {
            "success": True,
            "server": process_status.to_payload(),
            "enabledHarnesses": harnesses,
            "storedState": state.to_payload(),
        }
