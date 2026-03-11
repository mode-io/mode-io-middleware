#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:  # Python 3.14+
    from compression import zstd as _zstd_codec
except Exception:  # pragma: no cover
    _zstd_codec = None

from smoke_matrix.common import (
    check_required_commands as _check_required_commands,
    default_upstream_base_url,
    default_upstream_model,
    default_artifacts_root,
    default_repo_root,
    free_port as _free_port,
    parse_agents as _parse_agents,
    utc_stamp as _utc_stamp,
    wait_for_url as _wait_for_url,
    write_json as _write_json,
)
from smoke_matrix.openclaw_family import (
    SUPPORTED_OPENCLAW_FAMILIES,
    parse_openclaw_families as _parse_openclaw_families,
    resolve_openclaw_family_scenarios as _resolve_openclaw_family_scenarios,
)
from smoke_matrix.runner import (
    run_controller_disable_all as _run_controller_disable_all,
    run_controller_enable as _run_controller_enable,
    run_controller_inspect as _run_controller_inspect,
    run_agent_check as _run_agent_check,
    run_json_cli_command as _run_json_cli_command,
    run_openclaw_family_checks as _run_openclaw_family_checks,
    skipped_agent_report as _skipped_agent_report,
    start_logged_process as _start_logged_process,
    stop_process as _stop_process,
    close_handle as _close_handle,
)
from smoke_matrix.sandbox import (
    build_sandbox_env as _build_sandbox_env,
    build_sandbox_paths as _build_sandbox_paths,
    configure_opencode_supported_provider as _configure_opencode_supported_provider,
    resolve_opencode_smoke_model as _resolve_opencode_smoke_model,
    seed_codex_credentials as _seed_codex_credentials,
    seed_opencode_state as _seed_opencode_state,
    seed_openclaw_state as _seed_openclaw_state,
)
from smoke_matrix.runtime import prepare_runtime as _prepare_runtime
from modeio_middleware.cli.setup_lib.claude import apply_claude_settings_file

DEFAULT_UPSTREAM_BASE_URL = default_upstream_base_url(dict(os.environ))
DEFAULT_UPSTREAM_MODEL = default_upstream_model(dict(os.environ))


def _default_repo_root() -> Path:
    return default_repo_root(Path(__file__))


def _default_artifacts_root() -> Path:
    return default_artifacts_root(Path(__file__))


def _normalize_codex_model(model: str) -> str:
    normalized = model.strip()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    return normalized


def _resolve_codex_smoke_model(requested_model: str) -> str | None:
    normalized = _normalize_codex_model(requested_model)
    if not normalized or normalized == DEFAULT_UPSTREAM_MODEL:
        return None
    return normalized

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run isolated live smoke tests via the middleware controller for supported harnesses."
    )
    parser.add_argument(
        "--agents",
        default="opencode,openclaw,claude",
        help="Comma-separated harness list (codex,opencode,openclaw,claude)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_UPSTREAM_MODEL,
        help=(
            "OpenAI-compatible model name used only for generic non-preserve-provider checks; "
            "supported controller smoke uses the harness-selected model by default"
        ),
    )
    parser.add_argument(
        "--opencode-model",
        default="",
        help="Optional OpenCode model override in provider/model form; defaults to the seeded harness-selected model",
    )
    parser.add_argument(
        "--opencode-provider",
        default="",
        help="Optional exact OpenCode provider id to force in the sandbox for supported-provider smoke",
    )
    parser.add_argument(
        "--opencode-base-url",
        default="",
        help="Optional exact upstream base URL for --opencode-provider; required when forcing an OpenCode provider",
    )
    parser.add_argument(
        "--openclaw-families",
        default="current",
        help=(
            "OpenClaw families to exercise when openclaw is requested. Use 'current' "
            "to follow the harness-selected provider/model, or pass an explicit "
            f"comma-separated list ({', '.join(SUPPORTED_OPENCLAW_FAMILIES)})."
        ),
    )
    parser.add_argument(
        "--openclaw-openai-provider",
        default="",
        help="Optional OpenClaw provider id to force for the openai-completions family",
    )
    parser.add_argument(
        "--openclaw-openai-model",
        default="",
        help="Optional OpenClaw model id/ref to force for the openai-completions family",
    )
    parser.add_argument(
        "--openclaw-anthropic-provider",
        default="",
        help="Optional exact OpenClaw provider id to force for the anthropic-messages family",
    )
    parser.add_argument(
        "--openclaw-anthropic-model",
        default="",
        help="Optional exact OpenClaw model id/ref to force for the anthropic-messages family",
    )
    parser.add_argument(
        "--openclaw-anthropic-base-url",
        default="",
        help="Optional upstream base URL override used with an explicit anthropic provider selection",
    )
    parser.add_argument(
        "--claude-model",
        default="sonnet",
        help="Claude model alias/name used for claude smoke prompts",
    )
    parser.add_argument(
        "--upstream-base-url",
        default=DEFAULT_UPSTREAM_BASE_URL,
        help="Real upstream OpenAI-compatible base URL",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(_default_artifacts_root()),
        help="Artifact root directory (run-specific child dir is created)",
    )
    parser.add_argument(
        "--repo-root",
        default=str(_default_repo_root()),
        help="Repository root containing the smoke harness checkout",
    )
    parser.add_argument(
        "--install-mode",
        choices=("repo", "wheel", "path", "git"),
        default="repo",
        help=(
            "How the middleware runtime under test is launched: repo uses the current checkout, "
            "wheel installs a built wheel into a fresh temp venv, path installs from a local path, "
            "and git installs from a git URL"
        ),
    )
    parser.add_argument(
        "--install-target",
        default="",
        help="Optional path, wheel, or git URL used when --install-mode is wheel/path/git",
    )
    parser.add_argument(
        "--gateway-host", default="127.0.0.1", help="Gateway listen host"
    )
    parser.add_argument(
        "--gateway-port", type=int, default=0, help="Gateway listen port (0 = auto)"
    )
    parser.add_argument(
        "--tap-port", type=int, default=0, help="Tap proxy listen port (0 = auto)"
    )
    parser.add_argument(
        "--claude-tap-port",
        type=int,
        default=0,
        help="Claude hook tap proxy listen port (0 = auto)",
    )
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=300,
        help="Per-command timeout for setup and each agent command",
    )
    parser.add_argument(
        "--startup-timeout-seconds",
        type=int,
        default=40,
        help="Startup timeout for tap proxy and middleware health checks",
    )
    parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="Do not delete temporary sandbox directory after run (runtime install artifacts stay under the run artifacts dir)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    started_at = _utc_stamp()
    run_id = f"{started_at.lower()}-{os.getpid()}"

    repo_root = Path(args.repo_root).expanduser().resolve()
    artifacts_root = Path(args.artifacts_dir).expanduser().resolve()
    run_dir = artifacts_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_path = run_dir / "summary.json"
    tap_jsonl_path = run_dir / "tap-exchanges.jsonl"
    tap_stdout_path = run_dir / "tap-proxy.log"
    controller_config_path = run_dir / "controller" / "middleware.json"

    report: Dict[str, object] = {
        "success": False,
        "mode": "live-agents",
        "runId": run_id,
        "startedAt": started_at,
        "finishedAt": None,
        "upstream": {
            "baseUrl": args.upstream_base_url,
            "model": args.model,
            "source": "cli_or_default",
        },
        "agentModels": {
            "openaiCompatible": args.model,
            "opencode": args.opencode_model or None,
            "claude": args.claude_model,
        },
        "runtime": {
            "mode": args.install_mode,
            "installTarget": args.install_target or None,
        },
        "sandbox": {},
        "gateway": {},
        "tap": {
            "logPath": str(tap_jsonl_path),
            "stdoutPath": str(tap_stdout_path),
        },
        "opencodeTap": None,
        "inspect": None,
        "controller": None,
        "openclawFamilyScenarios": [],
        "gatewayChecks": [],
        "agents": [],
        "error": None,
    }

    sandbox_root = Path(tempfile.mkdtemp(prefix="modeio-middleware-smoke-"))
    paths = _build_sandbox_paths(sandbox_root)
    report["sandbox"] = {
        "root": str(paths["root"]),
        "home": str(paths["home"]),
        "claudeSettings": str(paths["claude_settings"]),
        "opencodeConfig": str(paths["opencode_config"]),
        "openclawConfig": str(paths["openclaw_config"]),
        "openclawModelsCache": str(paths["openclaw_models_cache"]),
        "controllerConfig": str(controller_config_path),
        "kept": bool(args.keep_sandbox),
    }

    claude_tap_process: Optional[subprocess.Popen] = None
    claude_tap_log_handle = None
    opencode_tap_process: Optional[subprocess.Popen] = None
    opencode_tap_log_handle = None
    runtime = None

    try:
        agents = _parse_agents(args.agents)
        needs_claude = "claude" in agents
        needs_openai_agents = any(agent in {"opencode", "openclaw"} for agent in agents)
        report["mode"] = (
            "live-agents"
            if needs_claude and needs_openai_agents
            else "live-claude"
            if needs_claude
            else "live-openai-agents"
        )
        missing_commands = _check_required_commands(agents)
        if missing_commands:
            raise RuntimeError(
                "missing required commands: " + ", ".join(missing_commands)
            )

        report["upstream"] = {
            **report["upstream"],
            "requestedBaseUrl": args.upstream_base_url,
            "requestedModel": args.model,
        }

        runtime = _prepare_runtime(
            repo_root=repo_root,
            run_dir=run_dir,
            timeout_seconds=args.command_timeout_seconds,
            install_mode=args.install_mode,
            install_target=args.install_target,
        )
        report["runtime"] = runtime.report

        for key in ("home", "xdg_config", "xdg_state", "xdg_cache", "openclaw_state"):
            paths[key].mkdir(parents=True, exist_ok=True)
        paths["claude_settings"].parent.mkdir(parents=True, exist_ok=True)
        paths["opencode_config"].parent.mkdir(parents=True, exist_ok=True)
        paths["openclaw_models_cache"].parent.mkdir(parents=True, exist_ok=True)

        seeded_codex = _seed_codex_credentials(Path.home(), paths["home"])
        seeded_opencode = _seed_opencode_state(Path.home(), paths)
        seeded_openclaw = _seed_openclaw_state(Path.home(), paths)
        report["sandbox"]["seededCodexFiles"] = seeded_codex
        report["sandbox"]["seededOpenCode"] = seeded_opencode
        report["sandbox"]["seededOpenClaw"] = seeded_openclaw
        report["sandbox"]["claudeUsesHostAuthContext"] = needs_claude
        if args.opencode_provider.strip():
            forced_provider = args.opencode_provider.strip()
            forced_model = args.opencode_model.strip()
            forced_base_url = args.opencode_base_url.strip()
            if not forced_model:
                raise RuntimeError(
                    "--opencode-model is required when --opencode-provider is set"
                )
            if not forced_base_url:
                raise RuntimeError(
                    "--opencode-base-url is required when --opencode-provider is set"
                )
            report["sandbox"]["forcedOpenCodeProvider"] = (
                _configure_opencode_supported_provider(
                    config_path=paths["opencode_config"],
                    provider_id=forced_provider,
                    model_ref=forced_model,
                    base_url=forced_base_url,
                )
            )
        resolved_opencode_model = (
            args.opencode_model.strip()
            or _resolve_opencode_smoke_model(
                config_path=paths["opencode_config"],
                state_path=paths["xdg_state"] / "opencode" / "model.json",
            )
        )
        report["agentModels"]["opencode"] = resolved_opencode_model

        openclaw_family_scenarios = []
        if "openclaw" in agents:
            openclaw_family_scenarios = _resolve_openclaw_family_scenarios(
                paths=paths,
                args=args,
            )
            report["openclawFamilyScenarios"] = [
                scenario.to_dict() for scenario in openclaw_family_scenarios
            ]

        gateway_port = args.gateway_port if args.gateway_port > 0 else _free_port()
        tap_port = args.tap_port if args.tap_port > 0 else _free_port()
        claude_tap_port = args.claude_tap_port if args.claude_tap_port > 0 else _free_port()
        gateway_base_url = f"http://{args.gateway_host}:{gateway_port}/v1"
        gateway_health_url = f"http://{args.gateway_host}:{gateway_port}/healthz"
        tap_base_url = f"http://{args.gateway_host}:{tap_port}"
        claude_gateway_root = f"http://{args.gateway_host}:{gateway_port}"
        claude_tap_base_url = f"http://{args.gateway_host}:{claude_tap_port}"

        env = _build_sandbox_env(
            runtime.env,
            paths,
            gateway_base_url=gateway_base_url,
        )

        report["inspect"] = _run_controller_inspect(
            controller_command=runtime.controller_command,
            repo_root=repo_root,
            env=env,
            controller_config_path=controller_config_path,
            opencode_config_path=paths["opencode_config"],
            openclaw_config_path=paths["openclaw_config"],
            openclaw_models_cache_path=paths["openclaw_models_cache"],
            claude_settings_path=paths["claude_settings"],
            codex_config_path=paths["codex_config"],
            timeout_seconds=args.command_timeout_seconds,
            host=args.gateway_host,
            port=gateway_port,
        )
        harness_reports = report.get("inspect", {}).get("harnesses", {})
        opencode_report = (
            harness_reports.get("opencode", {})
            if isinstance(harness_reports, dict)
            else {}
        )
        opencode_inspection = (
            opencode_report.get("inspection", {})
            if isinstance(opencode_report, dict)
            else {}
        )
        opencode_provider_id = (
            str(opencode_report.get("selection", {}).get("providerId") or opencode_inspection.get("providerId") or "").strip()
            if isinstance(opencode_inspection, dict)
            else ""
        )
        opencode_upstream_base_url = (
            str(opencode_inspection.get("upstreamBaseUrl") or "").strip()
            if isinstance(opencode_inspection, dict)
            else ""
        )

        if needs_claude:
            claude_tap_jsonl_path = run_dir / "claude-hook-exchanges.jsonl"
            claude_tap_stdout_path = run_dir / "claude-hook-tap.log"
            tap_command = [
                sys.executable,
                str(repo_root / "scripts" / "upstream_tap_proxy.py"),
                "--host",
                args.gateway_host,
                "--port",
                str(claude_tap_port),
                "--target-base-url",
                claude_gateway_root,
                "--log-jsonl",
                str(claude_tap_jsonl_path),
            ]
            claude_tap_process, claude_tap_log_handle = _start_logged_process(
                command=tap_command,
                cwd=repo_root,
                env=env,
                log_path=claude_tap_stdout_path,
            )
            if not _wait_for_url(
                f"{claude_tap_base_url}/healthz", timeout_seconds=args.startup_timeout_seconds
            ):
                raise RuntimeError("Claude hook tap proxy failed to become healthy")
            report["claudeTap"] = {
                "baseUrl": claude_tap_base_url,
                "port": claude_tap_port,
                "logPath": str(claude_tap_jsonl_path),
                "stdoutPath": str(claude_tap_stdout_path),
                "targetBaseUrl": claude_gateway_root,
            }
        else:
            report["claudeTap"] = {"skipped": True, "reason": "claude-not-requested"}

        if (
            "opencode" in agents
            and isinstance(opencode_report, dict)
            and opencode_report.get("controllerSupported") is True
            and opencode_provider_id
            and opencode_upstream_base_url
        ):
                opencode_tap_jsonl_path = run_dir / "opencode-tap-exchanges.jsonl"
                opencode_tap_stdout_path = run_dir / "opencode-tap.log"
                opencode_tap_port = _free_port()
                opencode_tap_base_url = f"http://{args.gateway_host}:{opencode_tap_port}"
                opencode_tap_command = [
                    sys.executable,
                    str(repo_root / "scripts" / "upstream_tap_proxy.py"),
                    "--host",
                    args.gateway_host,
                    "--port",
                    str(opencode_tap_port),
                    "--target-base-url",
                    opencode_upstream_base_url,
                    "--log-jsonl",
                    str(opencode_tap_jsonl_path),
                ]
                opencode_tap_process, opencode_tap_log_handle = _start_logged_process(
                    command=opencode_tap_command,
                    cwd=repo_root,
                    env=env,
                    log_path=opencode_tap_stdout_path,
                )
                if not _wait_for_url(
                    f"{opencode_tap_base_url}/healthz",
                    timeout_seconds=args.startup_timeout_seconds,
                ):
                    raise RuntimeError("opencode preserve-provider tap proxy failed to become healthy")
                report["opencodeTap"] = {
                    "baseUrl": opencode_tap_base_url,
                    "port": opencode_tap_port,
                    "logPath": str(opencode_tap_jsonl_path),
                    "stdoutPath": str(opencode_tap_stdout_path),
                    "targetBaseUrl": opencode_upstream_base_url,
                }
                report["sandbox"]["tapInjectedOpenCodeProvider"] = (
                    _configure_opencode_supported_provider(
                        config_path=paths["opencode_config"],
                        provider_id=opencode_provider_id,
                        model_ref=resolved_opencode_model,
                        base_url=opencode_tap_base_url,
                    )
                )

        report["gateway"] = {
            "baseUrl": gateway_base_url,
            "healthUrl": gateway_health_url,
            "host": args.gateway_host,
            "port": gateway_port,
            "configPath": str(controller_config_path),
        }

        controller_actions: Dict[str, object] = {}
        if "opencode" in agents:
            if isinstance(opencode_report, dict) and opencode_report.get("controllerSupported") is not True:
                report["agents"].append(
                    _skipped_agent_report(
                        agent="opencode",
                        report_name="opencode",
                        diagnostic=(
                            str(opencode_report.get("reason") or "").strip()
                            or "OpenCode selected provider is not currently supported by the middleware controller."
                        ),
                        product_ok=False,
                    )
                )
            else:
                controller_actions["opencode"] = _run_controller_enable(
                    controller_command=runtime.controller_command,
                    repo_root=repo_root,
                    env=env,
                    harness_name="opencode",
                    controller_config_path=controller_config_path,
                    opencode_config_path=paths["opencode_config"],
                    openclaw_config_path=paths["openclaw_config"],
                    openclaw_models_cache_path=paths["openclaw_models_cache"],
                    claude_settings_path=paths["claude_settings"],
                    codex_config_path=paths["codex_config"],
                    timeout_seconds=args.command_timeout_seconds,
                    host=args.gateway_host,
                    port=gateway_port,
                )
        if needs_claude:
            claude_report = (
                harness_reports.get("claude", {})
                if isinstance(harness_reports, dict)
                else {}
            )
            if isinstance(claude_report, dict) and claude_report.get("controllerSupported") is not True:
                report["agents"].append(
                    _skipped_agent_report(
                        agent="claude",
                        report_name="claude",
                        diagnostic=(
                            str(claude_report.get("reason") or "").strip()
                            or "Claude current state is not currently supported by the middleware controller."
                        ),
                        product_ok=False,
                    )
                )
            else:
                controller_actions["claude"] = _run_controller_enable(
                    controller_command=runtime.controller_command,
                    repo_root=repo_root,
                    env=env,
                    harness_name="claude",
                    controller_config_path=controller_config_path,
                    opencode_config_path=paths["opencode_config"],
                    openclaw_config_path=paths["openclaw_config"],
                    openclaw_models_cache_path=paths["openclaw_models_cache"],
                    claude_settings_path=paths["claude_settings"],
                    codex_config_path=paths["codex_config"],
                    timeout_seconds=args.command_timeout_seconds,
                    host=args.gateway_host,
                    port=gateway_port,
                )
                apply_claude_settings_file(
                    config_path=paths["claude_settings"],
                    gateway_base_url=claude_tap_base_url,
                    create_if_missing=True,
                )
        report["controller"] = {
            "actions": controller_actions,
            "status": (
                _run_json_cli_command(
                    command=[
                        *runtime.controller_command,
                        "status",
                        "--json",
                        "--config",
                        str(controller_config_path),
                    ],
                    cwd=repo_root,
                    env=env,
                    timeout_seconds=args.command_timeout_seconds,
                )[0]
                if controller_actions
                else None
            ),
        }

        report["gatewayChecks"] = [
            {
                "name": "generic-gateway-probes",
                "ok": True,
                "skipped": True,
                "reason": "disabled: middleware now relies on harness-owned auth and does not run generic managed-upstream gateway probes",
            }
        ]

        for index, agent in enumerate(agents, start=1):
            if agent == "openclaw":
                report["agents"].extend(
                    _run_openclaw_family_checks(
                        controller_command=runtime.controller_command,
                        repo_root=repo_root,
                        env=env,
                        controller_config_path=controller_config_path,
                        openclaw_config_path=paths["openclaw_config"],
                        openclaw_models_cache_path=paths["openclaw_models_cache"],
                        opencode_config_path=paths["opencode_config"],
                        claude_settings_path=paths["claude_settings"],
                        codex_config_path=paths["codex_config"],
                        run_dir=run_dir,
                        run_id=run_id,
                        timeout_seconds=args.command_timeout_seconds,
                        gateway_host=args.gateway_host,
                        gateway_port=gateway_port,
                        scenarios=openclaw_family_scenarios,
                    )
                )
                continue
            if agent == "opencode" and "opencode" not in controller_actions:
                continue
            if agent == "claude" and "claude" not in controller_actions:
                continue
            if agent == "codex":
                report["agents"].append(
                    _skipped_agent_report(
                        agent="codex",
                        report_name="codex",
                        diagnostic="Codex controller mode is not supported yet.",
                        product_ok=False,
                    )
                )
                continue

            report["agents"].append(
                _run_agent_check(
                    agent=agent,
                    index=index,
                    run_id=run_id,
                    report_name=None,
                    model=(
                        resolved_opencode_model
                        if agent == "opencode"
                        else args.model
                    ),
                    claude_model=args.claude_model,
                    repo_root=repo_root,
                    run_dir=run_dir,
                    env=env,
                    timeout_seconds=args.command_timeout_seconds,
                    claude_settings_path=paths["claude_settings"]
                    if agent == "claude"
                    else None,
                    tap_jsonl_path=(
                        claude_tap_jsonl_path
                        if (
                            agent == "claude"
                            and claude_tap_process is not None
                        )
                        else
                        opencode_tap_jsonl_path
                        if (
                            agent == "opencode"
                            and opencode_tap_process is not None
                        )
                        else tap_jsonl_path
                    ),
                )
            )

        report["success"] = all(
            bool(agent.get("productOk", agent.get("ok"))) for agent in report["agents"]
        )
    except Exception as error:
        report["success"] = False
        report["error"] = str(error)
    finally:
        try:
            if runtime is not None:
                _run_controller_disable_all(
                    controller_command=runtime.controller_command,
                    repo_root=repo_root,
                    env=env,
                    controller_config_path=controller_config_path,
                    timeout_seconds=args.command_timeout_seconds,
                )
        except Exception:
            pass
        _stop_process(opencode_tap_process)
        _stop_process(claude_tap_process)
        _close_handle(opencode_tap_log_handle)
        _close_handle(claude_tap_log_handle)

    report["finishedAt"] = _utc_stamp()
    _write_json(summary_path, report)

    if not args.keep_sandbox:
        shutil.rmtree(paths["root"], ignore_errors=True)

    print(f"[smoke-agent-matrix] summary: {summary_path}")
    for agent_report in report.get("agents", []):
        if not isinstance(agent_report, dict):
            continue
        tap = agent_report.get("tap")
        window = tap.get("window") if isinstance(tap, dict) else {}
        event_count = window.get("eventCount") if isinstance(window, dict) else None
        success_count = window.get("successCount") if isinstance(window, dict) else None
        print(
            "[smoke-agent-matrix] "
            f"{agent_report.get('reportName') or agent_report.get('name')}: "
            f"ok={agent_report.get('ok')} outcome={agent_report.get('outcome')} "
            f"exit={agent_report.get('exitCode')} tapEvents={event_count} tap2xx={success_count}"
        )

    for check in report.get("gatewayChecks", []):
        if not isinstance(check, dict):
            continue
        print(
            "[smoke-agent-matrix] "
            f"check {check.get('name')}: ok={check.get('ok')} outcome={check.get('outcome')} "
            f"status={check.get('status')}"
        )

    if report.get("error"):
        print(f"[smoke-agent-matrix] error: {report['error']}")

    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
