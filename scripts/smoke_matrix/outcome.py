from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class SmokeOutcome:
    tap_kind: str
    diagnostic: str | None
    outcome: str
    product_ok: bool


def classify_agent_outcome(
    *,
    agent: str,
    exit_code: int,
    transport_check_ok: bool,
    stdout_text: str,
    stderr_text: str,
    upstream_statuses: Sequence[int],
    expected_tap_path_fragment: str | None,
) -> SmokeOutcome:
    tap_kind = "claude_hook_tap" if agent == "claude" else "upstream_tap"
    if transport_check_ok:
        return SmokeOutcome(
            tap_kind=tap_kind,
            diagnostic=None,
            outcome="passed",
            product_ok=True,
        )

    diagnostic = None
    outcome = "product_failed"
    if agent == "codex":
        if "Missing scopes: api.responses.write" in stdout_text or "Missing scopes: api.responses.write" in stderr_text:
            diagnostic = "Codex native OAuth reaches upstream, but the current token lacks `api.responses.write`."
            outcome = "external_blocked"
        elif "refresh token was already used" in stderr_text:
            diagnostic = "Codex auth store needs a fresh login before native middleware smoke can pass."
            outcome = "warning"
    elif agent == "opencode":
        if "OpenAI API key is missing" in stdout_text:
            diagnostic = "OpenCode is still on the `openai` provider but this sandbox has no reusable `OPENAI_API_KEY`."
            outcome = "external_blocked"
    elif agent == "openclaw":
        route_label = (
            "Anthropic Messages"
            if expected_tap_path_fragment == "/v1/messages"
            else "chat completions"
        )
        if 429 in upstream_statuses:
            diagnostic = (
                f"OpenClaw native bridge reaches upstream {route_label}, "
                "but the current token/account is rate limited."
            )
            outcome = "external_blocked"
        elif 401 in upstream_statuses:
            diagnostic = (
                f"OpenClaw native bridge reaches upstream {route_label}, "
                "but the current auth is rejected for this route."
            )
            outcome = "external_blocked"

    if diagnostic is None:
        diagnostic = "Agent run did not produce the expected successful upstream traffic."

    return SmokeOutcome(
        tap_kind=tap_kind,
        diagnostic=diagnostic,
        outcome=outcome,
        product_ok=outcome in {"passed", "warning", "external_blocked"},
    )
