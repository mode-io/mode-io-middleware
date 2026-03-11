from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class OpenClawFamilyScenario:
    name: str
    family: str | None
    provider_key: str | None = None
    model_ref: str | None = None
    real_base_url: str | None = None
    api_family: str | None = None
    provider_fields: Dict[str, object] = field(default_factory=dict)
    expected_tap_path_fragment: str | None = None
    source: str | None = None
    skipped: bool = False
    error: bool = False
    reason: str | None = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "family": self.family,
            "providerKey": self.provider_key,
            "modelRef": self.model_ref,
            "realBaseUrl": self.real_base_url,
            "apiFamily": self.api_family,
            "providerFields": dict(self.provider_fields),
            "expectedTapPathFragment": self.expected_tap_path_fragment,
            "source": self.source,
            "skipped": self.skipped,
            "error": self.error,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SmokeAgentReport:
    name: str
    report_name: str
    exit_code: int
    timed_out: bool
    duration_ms: int
    stdout_path: str
    stderr_path: str
    token_in_output: bool
    tap_kind: str
    tap: Dict[str, Any]
    diagnostic: str | None
    ok: bool
    outcome: str
    product_ok: bool
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "name": self.name,
            "reportName": self.report_name,
            "exitCode": self.exit_code,
            "timedOut": self.timed_out,
            "durationMs": self.duration_ms,
            "stdoutPath": self.stdout_path,
            "stderrPath": self.stderr_path,
            "tokenInOutput": self.token_in_output,
            "tapKind": self.tap_kind,
            "tap": dict(self.tap),
            "diagnostic": self.diagnostic,
            "ok": self.ok,
            "outcome": self.outcome,
            "productOk": self.product_ok,
        }
        payload.update(self.extras)
        return payload
