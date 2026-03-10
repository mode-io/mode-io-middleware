#!/usr/bin/env python3

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple

from modeio_middleware.registry.loader import create_plugin_runtime
from modeio_middleware.registry.resolver import PluginRuntimeSpec
from modeio_middleware.runtime.base import PluginRuntime


@dataclass
class RuntimePoolEntry:
    key: Tuple[str, ...]
    runtime: PluginRuntime
    in_use: int = 0


class PluginRuntimeUnavailableError(RuntimeError):
    pass


class PluginRuntimeLease:
    def __init__(self, *, manager: "PluginRuntimeManager", key: Tuple[str, ...], entry: RuntimePoolEntry):
        self._manager = manager
        self._key = key
        self._entry = entry
        self._released = False

    @property
    def runtime(self) -> PluginRuntime:
        return self._entry.runtime

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._manager.release(self._key, self._entry)


class PluginRuntimeManager:
    """Pool and reuse plugin runtimes across requests."""

    DEFAULT_ACQUIRE_TIMEOUT_MS = 50
    MIN_ACQUIRE_TIMEOUT_MS = 10

    def __init__(self):
        self._condition = threading.Condition()
        self._runtimes: Dict[Tuple[str, ...], List[RuntimePoolEntry]] = {}

    def _acquire_timeout_seconds(self, spec: PluginRuntimeSpec) -> float:
        budget_ms = min(spec.timeout_ms.values()) if spec.timeout_ms else None
        if budget_ms is None:
            timeout_ms = self.DEFAULT_ACQUIRE_TIMEOUT_MS
        else:
            timeout_ms = min(
                self.DEFAULT_ACQUIRE_TIMEOUT_MS,
                max(self.MIN_ACQUIRE_TIMEOUT_MS, int(budget_ms * 0.25)),
            )
        return timeout_ms / 1000.0

    def _prune_unhealthy_idle_entries(
        self,
        entries: List[RuntimePoolEntry],
    ) -> List[PluginRuntime]:
        retired: List[PluginRuntime] = []
        healthy_entries: List[RuntimePoolEntry] = []
        for entry in entries:
            if entry.in_use == 0 and not entry.runtime.is_healthy():
                retired.append(entry.runtime)
                continue
            healthy_entries.append(entry)
        if len(healthy_entries) != len(entries):
            entries[:] = healthy_entries
        return retired

    def acquire(self, spec: PluginRuntimeSpec) -> PluginRuntimeLease:
        key = spec.runtime_cache_key()
        deadline = time.monotonic() + self._acquire_timeout_seconds(spec)
        retired_runtimes: List[PluginRuntime] = []
        with self._condition:
            entries = self._runtimes.setdefault(key, [])
            while True:
                retired_runtimes.extend(self._prune_unhealthy_idle_entries(entries))

                idle_entry = next((entry for entry in entries if entry.in_use == 0), None)
                if idle_entry is not None:
                    idle_entry.in_use += 1
                    lease = PluginRuntimeLease(manager=self, key=key, entry=idle_entry)
                    break

                if len(entries) < spec.pool_size:
                    idle_entry = RuntimePoolEntry(
                        key=key,
                        runtime=create_plugin_runtime(spec),
                    )
                    idle_entry.in_use = 1
                    entries.append(idle_entry)
                    lease = PluginRuntimeLease(manager=self, key=key, entry=idle_entry)
                    break

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PluginRuntimeUnavailableError(
                        f"plugin '{spec.name}' runtime pool timed out waiting for an idle runtime"
                    )
                self._condition.wait(timeout=remaining)
                entries = self._runtimes.setdefault(key, [])
        for runtime in retired_runtimes:
            try:
                runtime.shutdown()
            except Exception:
                continue
        return lease

    def release(self, key: Tuple[str, ...], entry: RuntimePoolEntry) -> None:
        retired_runtime = None
        with self._condition:
            entries = self._runtimes.get(key)
            if not entries:
                return
            for current in entries:
                if current is entry and current.in_use > 0:
                    current.in_use -= 1
                    if current.in_use == 0 and not current.runtime.is_healthy():
                        entries.remove(current)
                        retired_runtime = current.runtime
                    self._condition.notify_all()
                    break
        if retired_runtime is not None:
            try:
                retired_runtime.shutdown()
            except Exception:
                pass

    def shutdown(self) -> None:
        with self._condition:
            items = [
                entry.runtime
                for entries in self._runtimes.values()
                for entry in entries
            ]
            self._runtimes.clear()
            self._condition.notify_all()

        for runtime in reversed(items):
            try:
                runtime.shutdown()
            except Exception:
                continue
