from __future__ import annotations

from pathlib import Path
from typing import List


def _render_prompt(*, token: str, prompt_text: str | None) -> str:
    if prompt_text is None:
        return f"Reply with exactly this token and nothing else: {token}"
    if "{token}" in prompt_text:
        return prompt_text.replace("{token}", token)
    return (
        prompt_text.rstrip()
        + "\n\nWhen you are done, reply with exactly this token and nothing else: "
        + token
    )


def build_agent_command(
    *,
    agent: str,
    token: str,
    model: str,
    claude_model: str,
    work_dir: Path,
    codex_output_path: Path,
    claude_settings_path: Path | None,
    timeout_seconds: int,
    prompt_text: str | None = None,
) -> List[str]:
    prompt = _render_prompt(token=token, prompt_text=prompt_text)

    if agent == "codex":
        return [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "--model",
            model,
            "--output-last-message",
            str(codex_output_path),
            prompt,
        ]

    if agent == "opencode":
        if "/" not in model:
            raise ValueError(
                "OpenCode smoke requires an exact provider/model selection"
            )
        return [
            "opencode",
            "run",
            "--format",
            "json",
            "--model",
            model,
            "--dir",
            str(work_dir),
            prompt,
        ]

    if agent == "openclaw":
        return [
            "openclaw",
            "agent",
            "--local",
            "--json",
            "--session-id",
            f"modeio-smoke-{token.lower()}",
            "--thinking",
            "off",
            "--timeout",
            str(timeout_seconds),
            "--message",
            prompt,
        ]

    if agent == "claude":
        if claude_settings_path is None:
            raise ValueError("claude_settings_path is required for claude smoke runs")
        return [
            "claude",
            "--print",
            "--output-format",
            "text",
            "--permission-mode",
            "bypassPermissions",
            "--no-session-persistence",
            "--settings",
            str(claude_settings_path),
            "--model",
            claude_model,
            prompt,
        ]

    raise ValueError(f"unsupported agent: {agent}")
