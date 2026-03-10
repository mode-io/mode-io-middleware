#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional


@dataclass
class ProcessResult:
    status: int
    payload: Dict[str, Any]
    headers: Dict[str, str]


@dataclass
class StreamProcessResult:
    status: int
    headers: Dict[str, str]
    stream: Optional[Iterable[bytes]] = None
    payload: Optional[Dict[str, Any]] = None
