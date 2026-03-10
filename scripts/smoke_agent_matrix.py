#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:  # Python 3.14+
    from compression import zstd as _zstd_codec
except Exception:  # pragma: no cover
    _zstd_codec = None

from modeio_middleware.cli.setup_lib.upstream import OPENAI_UPSTREAM_BASE_URL
from smoke_matrix.common import (
    check_required_commands as _check_required_commands,
    default_upstream_base_url,
    default_upstream_model,
    default_artifacts_root,
    default_repo_root,
    free_port as _free_port,
    load_tap_events as _load_tap_events,
    parse_agents as _parse_agents,
    run_command_capture as _run_command_capture,
    tap_token_metrics as _tap_token_metrics,
    tap_window_metrics as _tap_window_metrics,
    utc_stamp as _utc_stamp,
    wait_for_url as _wait_for_url,
    write_json as _write_json,
    write_text as _write_text,
)
from smoke_matrix.openclaw_family import (
    DEFAULT_OPENCLAW_ANTHROPIC_BASE_URL,
    DEFAULT_OPENCLAW_ANTHROPIC_MODEL,
    DEFAULT_OPENCLAW_ANTHROPIC_PROVIDER,
    SUPPORTED_OPENCLAW_FAMILIES,
    parse_openclaw_families as _parse_openclaw_families,
    resolve_openclaw_family_scenarios as _resolve_openclaw_family_scenarios,
)
from smoke_matrix.runner import (
    request_with_bytes as _request_with_bytes,
    run_agent_check as _run_agent_check,
    run_doctor as _run_doctor,
    run_gateway_smoke_checks as _run_gateway_smoke_checks,
    run_json_cli_command as _run_json_cli_command,
    run_openclaw_family_checks as _run_openclaw_family_checks,
    run_setup as _run_setup,
    skipped_agent_report as _skipped_agent_report,
    start_logged_process as _start_logged_process,
    stop_process as _stop_process,
    close_handle as _close_handle,
)
from smoke_matrix.sandbox import (
    build_sandbox_env as _build_sandbox_env,
    build_sandbox_paths as _build_sandbox_paths,
    resolve_opencode_smoke_model as _resolve_opencode_smoke_model,
    seed_codex_credentials as _seed_codex_credentials,
    seed_opencode_state as _seed_opencode_state,
    seed_openclaw_state as _seed_openclaw_state,
)
from smoke_matrix.runtime import prepare_runtime as _prepare_runtime

DEFAULT_UPSTREAM_BASE_URL = default_upstream_base_url(dict(os.environ))
DEFAULT_UPSTREAM_MODEL = default_upstream_model(dict(os.environ))


def _default_repo_root() -> Path:
    return default_repo_root(Path(__file__))


def _default_artifacts_root() -> Path:
    return default_artifacts_root(Path(__file__))

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run isolated live smoke tests via codex/opencode/openclaw/claude through modeio-middleware."
    )
    parser.add_argument(
        "--agents",
        default="codex,opencode,openclaw,claude",
        help="Comma-separated agent list (codex,opencode,openclaw,claude)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_UPSTREAM_MODEL,
        help="OpenAI-compatible model name used for codex smoke prompts and as the fallback default elsewhere",
    )
    parser.add_argument(
        "--opencode-model",
        default="",
        help="Optional OpenCode model override in provider/model form; defaults to the seeded harness-selected model",
    )
    parser.add_argument(
        "--openclaw-families",
        default="openai-completions,anthropic-messages",
        help=(
            "Comma-separated OpenClaw families to exercise when openclaw is requested "
            f"({', '.join(SUPPORTED_OPENCLAW_FAMILIES)})"
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
        default=DEFAULT_OPENCLAW_ANTHROPIC_PROVIDER,
        help="OpenClaw provider id used for the anthropic-messages family",
    )
    parser.add_argument(
        "--openclaw-anthropic-model",
        default=DEFAULT_OPENCLAW_ANTHROPIC_MODEL,
        help="OpenClaw model id/ref used for the anthropic-messages family",
    )
    parser.add_argument(
        "--openclaw-anthropic-base-url",
        default=DEFAULT_OPENCLAW_ANTHROPIC_BASE_URL,
        help="Upstream base URL used when synthesizing the OpenClaw anthropic family provider",
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
    codex_tap_jsonl_path = run_dir / "codex-tap-exchanges.jsonl"
    codex_tap_stdout_path = run_dir / "codex-tap.log"
    claude_tap_jsonl_path = run_dir / "claude-hook-exchanges.jsonl"
    claude_tap_stdout_path = run_dir / "claude-hook-tap.log"
    gateway_log_path = run_dir / "gateway.log"
    setup_payload_path = run_dir / "setup-report.json"

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
            "codex": args.model,
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
        "codexNativeTap": None,
        "claudeHookTap": None,
        "doctor": None,
        "setup": None,
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
        "kept": bool(args.keep_sandbox),
    }

    tap_process: Optional[subprocess.Popen] = None
    tap_log_handle = None
    codex_tap_process: Optional[subprocess.Popen] = None
    codex_tap_log_handle = None
    claude_tap_process: Optional[subprocess.Popen] = None
    claude_tap_log_handle = None
    gateway_process: Optional[subprocess.Popen] = None
    gateway_log_handle = None

    try:
        agents = _parse_agents(args.agents)
        needs_claude = "claude" in agents
        needs_openai_agents = any(agent != "claude" for agent in agents)
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
        resolved_opencode_model = (
            args.opencode_model.strip()
            or _resolve_opencode_smoke_model(
                config_path=paths["opencode_config"],
                state_path=paths["xdg_state"] / "opencode" / "model.json",
                fallback_model=f"openai/{args.model}" if "/" not in args.model else args.model,
            )
        )
        report["agentModels"]["opencode"] = resolved_opencode_model

        openclaw_family_scenarios: List[Dict[str, object]] = []
        if "openclaw" in agents:
            openclaw_family_scenarios = _resolve_openclaw_family_scenarios(
                paths=paths,
                args=args,
            )
            report["openclawFamilyScenarios"] = [
                {
                    key: scenario.get(key)
                    for key in (
                        "name",
                        "family",
                        "providerKey",
                        "modelRef",
                        "realBaseUrl",
                        "apiFamily",
                        "expectedTapPathFragment",
                        "source",
                        "skipped",
                        "reason",
                    )
                    if key in scenario
                }
                for scenario in openclaw_family_scenarios
            ]

        gateway_port = args.gateway_port if args.gateway_port > 0 else _free_port()
        tap_port = args.tap_port if args.tap_port > 0 else _free_port()
        gateway_base_url = f"http://{args.gateway_host}:{gateway_port}/v1"
        gateway_health_url = f"http://{args.gateway_host}:{gateway_port}/healthz"
        tap_base_url = f"http://{args.gateway_host}:{tap_port}"
        gateway_root_url = gateway_base_url.rsplit("/v1", 1)[0]

        env = _build_sandbox_env(
            runtime.env,
            paths,
            gateway_base_url=gateway_base_url,
        )

        report["doctor"] = _run_doctor(
            setup_command=runtime.setup_command,
            repo_root=repo_root,
            env=env,
            agents=agents,
            gateway_base_url=gateway_base_url,
            opencode_config_path=paths["opencode_config"],
            openclaw_config_path=paths["openclaw_config"],
            openclaw_models_cache_path=paths["openclaw_models_cache"],
            claude_settings_path=paths["claude_settings"],
            timeout_seconds=args.command_timeout_seconds,
        )
        native_clients_report = report.get("doctor", {}).get("nativeClients", {})
        opencode_native_report = (
            native_clients_report.get("opencode", {})
            if isinstance(native_clients_report, dict)
            else {}
        )
        opencode_transport = (
            opencode_native_report.get("transport")
            if isinstance(opencode_native_report, dict)
            else None
        )

        gateway_upstream_chat_url = f"{OPENAI_UPSTREAM_BASE_URL}/chat/completions"
        gateway_upstream_responses_url = f"{OPENAI_UPSTREAM_BASE_URL}/responses"
        if needs_openai_agents:
            tap_command = [
                sys.executable,
                str(repo_root / "scripts" / "upstream_tap_proxy.py"),
                "--host",
                args.gateway_host,
                "--port",
                str(tap_port),
                "--target-base-url",
                args.upstream_base_url,
                "--log-jsonl",
                str(tap_jsonl_path),
            ]
            tap_process, tap_log_handle = _start_logged_process(
                command=tap_command,
                cwd=repo_root,
                env=env,
                log_path=tap_stdout_path,
            )
            if not _wait_for_url(
                f"{tap_base_url}/healthz", timeout_seconds=args.startup_timeout_seconds
            ):
                raise RuntimeError("tap proxy failed to become healthy")
            gateway_upstream_chat_url = f"{tap_base_url}/v1/chat/completions"
            gateway_upstream_responses_url = f"{tap_base_url}/v1/responses"
            report["tap"]["baseUrl"] = tap_base_url
            report["tap"]["port"] = tap_port
            if "codex" in agents:
                codex_tap_port = _free_port()
                codex_tap_base_url = f"http://{args.gateway_host}:{codex_tap_port}"
                codex_tap_command = [
                    sys.executable,
                    str(repo_root / "scripts" / "upstream_tap_proxy.py"),
                    "--host",
                    args.gateway_host,
                    "--port",
                    str(codex_tap_port),
                    "--target-base-url",
                    "https://chatgpt.com/backend-api/codex",
                    "--log-jsonl",
                    str(codex_tap_jsonl_path),
                ]
                codex_tap_process, codex_tap_log_handle = _start_logged_process(
                    command=codex_tap_command,
                    cwd=repo_root,
                    env=env,
                    log_path=codex_tap_stdout_path,
                )
                if not _wait_for_url(
                    f"{codex_tap_base_url}/healthz",
                    timeout_seconds=args.startup_timeout_seconds,
                ):
                    raise RuntimeError("codex native tap proxy failed to become healthy")
                env["MODEIO_CODEX_NATIVE_BASE_URL"] = codex_tap_base_url
                report["codexNativeTap"] = {
                    "baseUrl": codex_tap_base_url,
                    "port": codex_tap_port,
                    "logPath": str(codex_tap_jsonl_path),
                    "stdoutPath": str(codex_tap_stdout_path),
                    "targetBaseUrl": "https://chatgpt.com/backend-api/codex",
                }
        else:
            report["tap"]["skipped"] = True
            report["tap"]["reason"] = "openai-compatible-agents-not-requested"

        gateway_command = [
            *runtime.gateway_command,
            "--host",
            args.gateway_host,
            "--port",
            str(gateway_port),
            "--upstream-chat-url",
            gateway_upstream_chat_url,
            "--upstream-responses-url",
            gateway_upstream_responses_url,
        ]
        gateway_process, gateway_log_handle = _start_logged_process(
            command=gateway_command,
            cwd=repo_root,
            env=env,
            log_path=gateway_log_path,
        )
        if not _wait_for_url(
            gateway_health_url, timeout_seconds=args.startup_timeout_seconds
        ):
            raise RuntimeError("middleware gateway failed to become healthy")

        report["gateway"] = {
            "baseUrl": gateway_base_url,
            "healthUrl": gateway_health_url,
            "logPath": str(gateway_log_path),
            "host": args.gateway_host,
            "port": gateway_port,
        }

        claude_gateway_base_url = gateway_base_url
        if needs_claude:
            claude_tap_port = (
                args.claude_tap_port if args.claude_tap_port > 0 else _free_port()
            )
            claude_tap_base_url = f"http://{args.gateway_host}:{claude_tap_port}"
            claude_tap_command = [
                sys.executable,
                str(repo_root / "scripts" / "upstream_tap_proxy.py"),
                "--host",
                args.gateway_host,
                "--port",
                str(claude_tap_port),
                "--target-base-url",
                gateway_root_url,
                "--log-jsonl",
                str(claude_tap_jsonl_path),
            ]
            claude_tap_process, claude_tap_log_handle = _start_logged_process(
                command=claude_tap_command,
                cwd=repo_root,
                env=env,
                log_path=claude_tap_stdout_path,
            )
            if not _wait_for_url(
                f"{claude_tap_base_url}/healthz",
                timeout_seconds=args.startup_timeout_seconds,
            ):
                raise RuntimeError("claude hook tap proxy failed to become healthy")
            claude_gateway_base_url = f"{claude_tap_base_url}/v1"
            report["claudeHookTap"] = {
                "baseUrl": claude_tap_base_url,
                "port": claude_tap_port,
                "logPath": str(claude_tap_jsonl_path),
                "stdoutPath": str(claude_tap_stdout_path),
                "targetBaseUrl": gateway_root_url,
            }

        setup_payload = _run_setup(
            setup_command=runtime.setup_command,
            repo_root=repo_root,
            env=env,
            gateway_base_url=gateway_base_url,
            claude_gateway_base_url=claude_gateway_base_url,
            opencode_config_path=paths["opencode_config"],
            openclaw_config_path=paths["openclaw_config"],
            openclaw_models_cache_path=paths["openclaw_models_cache"],
            claude_settings_path=paths["claude_settings"],
            timeout_seconds=args.command_timeout_seconds,
            configure_openai_clients=needs_openai_agents,
            configure_claude=needs_claude,
        )
        report["setup"] = setup_payload
        _write_json(setup_payload_path, setup_payload)

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
                        setup_command=runtime.setup_command,
                        repo_root=repo_root,
                        env=env,
                        gateway_base_url=gateway_base_url,
                        openclaw_config_path=paths["openclaw_config"],
                        openclaw_models_cache_path=paths["openclaw_models_cache"],
                        run_dir=run_dir,
                        run_id=run_id,
                        timeout_seconds=args.command_timeout_seconds,
                        gateway_host=args.gateway_host,
                        scenarios=openclaw_family_scenarios,
                    )
                )
                continue
            if (
                agent == "opencode"
                and isinstance(opencode_native_report, dict)
                and opencode_native_report.get("supported") is False
            ):
                report["agents"].append(
                    _skipped_agent_report(
                        agent="opencode",
                        report_name="opencode",
                        diagnostic=(
                            str(opencode_native_report.get("reason") or "").strip()
                            or "OpenCode selected provider is not redirectable through middleware."
                        ),
                    )
                )
                continue

            report["agents"].append(
                _run_agent_check(
                    agent=agent,
                    index=index,
                    run_id=run_id,
                    report_name=None,
                    model=resolved_opencode_model if agent == "opencode" else args.model,
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
                        if agent == "claude"
                        else codex_tap_jsonl_path
                        if (
                            codex_tap_process is not None
                            and (
                                agent == "codex"
                                or (agent == "opencode" and opencode_transport == "codex_native")
                            )
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
        _stop_process(claude_tap_process)
        _stop_process(codex_tap_process)
        _stop_process(gateway_process)
        _stop_process(tap_process)
        _close_handle(claude_tap_log_handle)
        _close_handle(codex_tap_log_handle)
        _close_handle(gateway_log_handle)
        _close_handle(tap_log_handle)

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
