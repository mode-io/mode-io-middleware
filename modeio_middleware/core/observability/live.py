#!/usr/bin/env python3

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LiveEvent:
    event: str
    data: dict[str, Any]


class LiveSubscriber:
    def __init__(self, *, max_queue_size: int):
        self._queue: queue.Queue[LiveEvent | None] = queue.Queue(
            maxsize=max(1, max_queue_size)
        )
        self._closed = False
        self._lock = threading.Lock()

    def publish(self, event: LiveEvent) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(event)
                except queue.Full:
                    pass

    def get(self, timeout: float) -> LiveEvent | None:
        try:
            return self._queue.get(timeout=max(timeout, 0.01))
        except queue.Empty:
            return None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
