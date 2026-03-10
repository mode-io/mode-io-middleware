#!/usr/bin/env python3

from __future__ import annotations

from typing import Any, Dict

from modeio_middleware.core.hook_envelope import HookEnvelope


class PluginRuntime:
    runtime_name = "base"

    def invoke(self, hook_name: str, hook_input: HookEnvelope | Dict[str, Any]) -> Any:
        raise NotImplementedError

    def is_healthy(self) -> bool:
        return True

    def shutdown(self) -> None:
        return
