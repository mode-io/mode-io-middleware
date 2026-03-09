"""Typed runtime services used by the middleware engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modeio_middleware.core.observability.service import RequestJournalService
from modeio_middleware.core.services.telemetry import PluginTelemetry


@dataclass(frozen=True)
class EngineServices:
    telemetry: PluginTelemetry
    request_journal: RequestJournalService | None

    def as_plugin_services(self) -> dict[str, Any]:
        services: dict[str, Any] = {"telemetry": self.telemetry}
        if self.request_journal is not None:
            services["request_journal"] = self.request_journal
        return services
