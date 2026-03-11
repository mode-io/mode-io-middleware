#!/usr/bin/env python3

from __future__ import annotations

from .base import HarnessAdapter
from .claude import ClaudeHarnessAdapter
from .codex import CodexHarnessAdapter
from .opencode import OpenCodeHarnessAdapter
from .openclaw import OpenClawHarnessAdapter


class HarnessAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, HarnessAdapter] = {
            "codex": CodexHarnessAdapter(),
            "opencode": OpenCodeHarnessAdapter(),
            "openclaw": OpenClawHarnessAdapter(),
            "claude": ClaudeHarnessAdapter(),
        }

    def adapter_names(self) -> tuple[str, ...]:
        return tuple(self._adapters.keys())

    def adapter_for(self, harness_name: str) -> HarnessAdapter:
        normalized = str(harness_name or "").strip().lower().replace("_", "-")
        try:
            return self._adapters[normalized]
        except KeyError as error:
            raise KeyError(f"unknown harness adapter: {harness_name}") from error
