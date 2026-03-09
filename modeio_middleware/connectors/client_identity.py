#!/usr/bin/env python3

from __future__ import annotations

from typing import Mapping

CLIENT_CLAUDE_CODE = "claude_code"
CLIENT_CODEX = "codex"
CLIENT_OPENCODE = "opencode"
CLIENT_OPENCLAW = "openclaw"
CLIENT_UNKNOWN = "unknown"

KNOWN_CLIENTS = {
    CLIENT_CLAUDE_CODE,
    CLIENT_CODEX,
    CLIENT_OPENCODE,
    CLIENT_OPENCLAW,
    CLIENT_UNKNOWN,
}


def _header(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return str(value)
    return ""


def _normalize_explicit_client(raw: str) -> str | None:
    value = raw.strip().lower().replace("-", "_")
    if value in KNOWN_CLIENTS:
        return value
    return None


def detect_openai_client_name(incoming_headers: Mapping[str, str]) -> str:
    explicit = _normalize_explicit_client(_header(incoming_headers, "x-modeio-client"))
    if explicit is not None:
        return explicit

    observed = " ".join(
        part
        for part in (
            _header(incoming_headers, "user-agent"),
            _header(incoming_headers, "x-openai-client-user-agent"),
            _header(incoming_headers, "x-stainless-user-agent"),
        )
        if part
    ).lower()

    if not observed:
        return CLIENT_UNKNOWN
    if "opencode" in observed:
        return CLIENT_OPENCODE
    if any(
        token in observed for token in ("openclaw", "clawdbot", "moltbot", "moldbot")
    ):
        return CLIENT_OPENCLAW
    if "codex" in observed:
        return CLIENT_CODEX
    return CLIENT_UNKNOWN
