#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modeio_middleware.core.observability.models import ChangeSummary


@dataclass
class _DiffAccumulator:
    sample_limit: int
    add_count: int = 0
    remove_count: int = 0
    replace_count: int = 0
    sample_paths: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.sample_paths = []

    def _remember(self, path: str) -> None:
        if len(self.sample_paths) < self.sample_limit:
            self.sample_paths.append(path or "/")

    def add(self, path: str) -> None:
        self.add_count += 1
        self._remember(path)

    def remove(self, path: str) -> None:
        self.remove_count += 1
        self._remember(path)

    def replace(self, path: str) -> None:
        self.replace_count += 1
        self._remember(path)

    def build(self) -> ChangeSummary:
        return ChangeSummary(
            changed=(self.add_count + self.remove_count + self.replace_count) > 0,
            add_count=self.add_count,
            remove_count=self.remove_count,
            replace_count=self.replace_count,
            sample_paths=tuple(self.sample_paths),
        )


def _join(path: str, segment: str) -> str:
    if not path:
        return f"/{segment}"
    return f"{path}/{segment}"


def _walk(before: Any, after: Any, *, path: str, acc: _DiffAccumulator) -> None:
    if before is None and after is None:
        return
    if before is None:
        acc.add(path)
        return
    if after is None:
        acc.remove(path)
        return

    if type(before) is not type(after):
        acc.replace(path)
        return

    if isinstance(before, dict):
        before_keys = set(before.keys())
        after_keys = set(after.keys())
        for key in sorted(before_keys - after_keys):
            acc.remove(_join(path, str(key)))
        for key in sorted(after_keys - before_keys):
            acc.add(_join(path, str(key)))
        for key in sorted(before_keys & after_keys):
            _walk(before[key], after[key], path=_join(path, str(key)), acc=acc)
        return

    if isinstance(before, list):
        shared = min(len(before), len(after))
        for index in range(shared):
            _walk(before[index], after[index], path=_join(path, str(index)), acc=acc)
        for index in range(shared, len(before)):
            acc.remove(_join(path, str(index)))
        for index in range(shared, len(after)):
            acc.add(_join(path, str(index)))
        return

    if before != after:
        acc.replace(path)


def summarize_change(
    before: dict[str, Any] | None, after: dict[str, Any] | None, *, sample_limit: int
) -> ChangeSummary:
    if before is None or after is None:
        if before is None and after is None:
            return ChangeSummary(changed=False)
        acc = _DiffAccumulator(sample_limit=max(sample_limit, 1))
        _walk(before, after, path="", acc=acc)
        return acc.build()

    acc = _DiffAccumulator(sample_limit=max(sample_limit, 1))
    _walk(before, after, path="", acc=acc)
    return acc.build()
